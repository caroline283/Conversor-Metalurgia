import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import os
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURAÇÃO DA PÁGINA (VISUAL) ---
st.set_page_config(
    page_title="Metalurgia System", 
    layout="wide", 
    page_icon="🏗️",
    initial_sidebar_state="expanded"
)

# --- CSS PERSONALIZADO (LARANJA E CINZA) ---
st.markdown("""
    <style>
    /* Estilo dos Cards de Métrica */
    div[data-testid="stMetric"] {
        background-color: #F0F2F6; /* Fundo Cinza Claro */
        border-left: 5px solid #FF5722; /* Borda Laranja na esquerda */
        padding: 15px;
        border-radius: 5px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
    }
    /* Cor do Título Principal (Laranja Industrial) */
    h1 { color: #FF5722; }
    
    /* Ajuste de tabelas */
    .stDataFrame { border: 1px solid #ddd; }
    
    /* Botões Primários (Laranja) */
    div.stButton > button:first-child {
        background-color: #FF5722;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 0. CONEXÃO COM GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 1. CARREGAMENTO DE DADOS ---
def carregar_dados_iniciais():
    # Definição dos dados padrão
    default_mapeamento = pd.DataFrame([
        {'texto_contido': 'CONFIGURAÇÃO DO MÓDULO', 'tipo': 'IGNORAR'},
        {'texto_contido': 'Capa do pé condutor 330', 'tipo': 'IGNORAR'},
        {'texto_contido': 'Leito metálico 920 Bate Forte', 'tipo': 'CONJUNTO'},
        {'texto_contido': 'Pé Condutor 330', 'tipo': 'CONJUNTO'},
        {'texto_contido': 'Pé 50x50', 'tipo': 'tubo 50x50'},
        {'texto_contido': 'Tubo Frontal Plataforma', 'tipo': 'tubo 50x20'},
        {'texto_contido': 'Tubo Lateral Squadra', 'tipo': 'tubo 50x50'},
        {'texto_contido': 'CHAPA', 'tipo': 'CH_PLANA'},
        {'texto_contido': 'Chapa 3mm', 'tipo': 'CH_PLANA'},
    ])
    default_pesos_metro = pd.DataFrame([
        {'secao': '50x20', 'peso_kg_m': 1.2638},
        {'secao': '25x25', 'peso_kg_m': 0.887},
        {'secao': '20x20', 'peso_kg_m': 0.7533},
        {'secao': '100x100', 'peso_kg_m': 6.275},
        {'secao': '50x50', 'peso_kg_m': 2.2691},
    ])
    default_pesos_conjunto = pd.DataFrame([
        {'nome_conjunto': 'Leito metálico 920 Bate Forte', 'peso_unit_kg': 2.5},
        {'nome_conjunto': 'Pé Condutor 330 para mesas com estrutura metálica', 'peso_unit_kg': 12.0},
    ])

    try:
        df_map = conn.read(worksheet="MAPEAMENTO_TIPO", ttl=5)
        df_metro = conn.read(worksheet="PESO_POR_METRO", ttl=5)
        df_conj = conn.read(worksheet="PESO_CONJUNTO", ttl=5)
        
        if 'db_mapeamento' not in st.session_state: st.session_state.db_mapeamento = df_map
        if 'db_pesos_metro' not in st.session_state: st.session_state.db_pesos_metro = df_metro
        if 'db_pesos_conjunto' not in st.session_state: st.session_state.db_pesos_conjunto = df_conj
        
    except Exception:
        if 'db_mapeamento' not in st.session_state: st.session_state.db_mapeamento = default_mapeamento
        if 'db_pesos_metro' not in st.session_state: st.session_state.db_pesos_metro = default_pesos_metro
        if 'db_pesos_conjunto' not in st.session_state: st.session_state.db_pesos_conjunto = default_pesos_conjunto

carregar_dados_iniciais()

if 'df_dados' not in st.session_state:
    st.session_state.df_dados = pd.DataFrame()

# --- 2. FUNÇÕES AUXILIARES ---
def salvar_na_nuvem():
    try:
        with st.spinner("Salvando dados no Google Sheets..."):
            conn.update(worksheet="MAPEAMENTO_TIPO", data=st.session_state.db_mapeamento)
            conn.update(worksheet="PESO_POR_METRO", data=st.session_state.db_pesos_metro)
            conn.update(worksheet="PESO_CONJUNTO", data=st.session_state.db_pesos_conjunto)
        st.success("✅ Dados salvos na nuvem com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# --- 3. MOTOR DE CÁLCULO ---
def calcular_final(df_input):
    map_rules = st.session_state.db_mapeamento.to_dict('records')
    dict_metro = dict(zip(st.session_state.db_pesos_metro['secao'], st.session_state.db_pesos_metro['peso_kg_m']))
    dict_conjunto = dict(zip(st.session_state.db_pesos_conjunto['nome_conjunto'], st.session_state.db_pesos_conjunto['peso_unit_kg']))
    
    densidade = 7.85
    resultados = []
    
    for _, row in df_input.iterrows():
        desc = str(row['DESCRIÇÃO'])
        qtd = float(row['QTD']) if row['QTD'] else 0.0
        
        tipo_final = "DESCONHECIDO"
        for regra in map_rules:
            if str(regra['texto_contido']).upper() in desc.upper():
                tipo_final = regra['tipo']
                break
        
        if tipo_final == "DESCONHECIDO":
            if "TUBO" in desc.upper(): tipo_final = "tubo GENERICO"
            elif "CHAPA" in desc.upper(): tipo_final = "CH_PLANA"

        peso_unit = 0.0
        metodo = "-"
        
        medida_mm = 0.0
        try:
            txt = str(row['MEDIDA']).lower().replace('mm','').strip()
            medida_mm = float(txt) if txt else 0.0
        except: pass

        if tipo_final == 'CONJUNTO':
            for nome, peso in dict_conjunto.items():
                if nome.upper() in desc.upper():
                    peso_unit = peso
                    metodo = "Tabela (Conjunto)"
                    break
        elif 'tubo' in tipo_final.lower():
            secao = tipo_final.lower().replace('tubo ', '').strip()
            if secao == "generico":
                busca = re.search(r'(\d+x\d+)', desc)
                if busca: secao = busca.group(1)
            peso_m = dict_metro.get(secao, 0.0)
            if peso_m > 0 and medida_mm > 0:
                peso_unit = (medida_mm/1000) * peso_m
                metodo = f"Linear ({secao})"
        elif tipo_final == 'CH_PLANA':
            dim = re.findall(r'(\d+)x(\d+)', desc)
            if dim:
                l1, l2 = map(float, dim[-1])
                peso_unit = (l1 * l2 * 3.0 * densidade) / 1000000
                metodo = f"Área ({l1}x{l2})"
        
        resultados.append({
            "QTD": qtd,
            "DESCRIÇÃO": desc,
            "MEDIDA": row['MEDIDA'],
            "TIPO_DETECTADO": tipo_final,
            "MÉTODO": metodo,
            "PESO_TOTAL": round(peso_unit * qtd, 3)
        })
        
    return pd.DataFrame(resultados)


# --- 4. INTERFACE VISUAL ---

# BARRA LATERAL (LOGO E NOME)
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.markdown("<h1 style='text-align: center; color: #FF5722;'>🏗️</h1>", unsafe_allow_html=True)
        
    st.markdown("### Metalurgia System 3.0")
    st.markdown("---")
    st.info("**Instruções:**\n1. Suba o PDF na aba Calculadora.\n2. Edite se necessário.\n3. Baixe o Excel final.")

# TÍTULO PRINCIPAL
st.title("Sistema de Cálculo de Estruturas")
st.markdown("---")

aba_calc, aba_db = st.tabs(["📋 Calculadora de Pedidos", "🛠️ Editor da Base de Dados"])

# === ABA 1: CALCULADORA ===
with aba_calc:
    col_up, col_btn = st.columns([3, 1])
    with col_up:
        uploaded_pdf = st.file_uploader("Suba o Relatório PDF do Pedido", type="pdf")
    
    if uploaded_pdf:
        if st.session_state.df_dados.empty:
            with st.spinner("Lendo PDF..."):
                itens = []
                with pdfplumber.open(uploaded_pdf) as pdf:
                    for page in pdf.pages:
                        tabs = page.extract_tables()
                        for tab in tabs:
                            for row in tab:
                                if len(row) > 3 and row[0] and str(row[0]).strip().replace('.','').isdigit():
                                    itens.append({
                                        "QTD": float(row[0]),
                                        "DESCRIÇÃO": row[1].replace('\n', ' '),
                                        "MEDIDA": row[3],
                                        "COR": row[2]
                                    })
                st.session_state.df_dados = pd.DataFrame(itens)

    if not st.session_state.df_dados.empty:
        st.success(f"✅ PDF Carregado: {len(st.session_state.df_dados)} itens encontrados.")
        
        # Container com borda para o editor
        with st.container(border=True):
            st.markdown("#### 🔍 Verifique e Edite o Pedido")
            df_editado = st.data_editor(
                st.session_state.df_dados,
                num_rows="dynamic",
                use_container_width=True,
                key="editor_pedido"
            )
        
        st.write("") # Espaço
        if st.button("🚀 Calcular Pesos Agora", type="primary", use_container_width=True):
            df_res = calcular_final(df_editado)
            
            st.markdown("---")
            st.markdown("### 📊 Resultado Final")
            
            # Métricas em Cards Estilizados (Agora com borda Laranja)
            total = df_res['PESO_TOTAL'].sum()
            qtd_itens = len(df_res)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Peso Total (kg)", f"{total:.2f}")
            c2.metric("Itens Calculados", qtd_itens)
            c3.metric("Média por Item", f"{total/qtd_itens:.2f} kg")
            
            st.dataframe(df_res, use_container_width=True)
            
            buffer_res = io.BytesIO()
            with pd.ExcelWriter(buffer_res, engine='openpyxl') as writer:
                df_res.to_excel(writer, index=False)
            
            st.download_button("📥 Baixar Planilha de Pesos", buffer_res.getvalue(), "Resultado_Calculo.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        
        if st.button("🗑️ Limpar Pedido Atual"):
            st.session_state.df_dados = pd.DataFrame()
            st.rerun()

# === ABA 2: EDITOR DA BASE DE DADOS ===
with aba_db:
    st.header("Gerenciar Regras de Cálculo (Nuvem)")
    
    col_save, col_info = st.columns([1, 2])
    with col_save:
        if st.button("☁️ Salvar Alterações na Nuvem", type="primary"):
            salvar_na_nuvem()
    
    with st.container(border=True):
        tab1, tab2, tab3 = st.tabs(["🔀 Mapeamento", "⚖️ Pesos Tubos", "📦 Pesos Conjuntos"])
        
        with tab1:
            st.caption("Regras de inteligência para identificar peças:")
            st.session_state.db_mapeamento = st.data_editor(st.session_state.db_mapeamento, num_rows="dynamic", use_container_width=True, key="edit_map")
            
        with tab2:
            st.caption("Tabela de pesos por metro:")
            st.session_state.db_pesos_metro = st.data_editor(st.session_state.db_pesos_metro, num_rows="dynamic", use_container_width=True, key="edit_metro")
            
        with tab3:
            st.caption("Tabela de pesos unitários:")
            st.session_state.db_pesos_conjunto = st.data_editor(st.session_state.db_pesos_conjunto, num_rows="dynamic", use_container_width=True, key="edit_conj")
