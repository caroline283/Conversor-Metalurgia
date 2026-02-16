import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Metalurgia Calc System V3", layout="wide", page_icon="🏗️")

# --- 1. GERENCIAMENTO DE ESTADO ---
# Inicializa as variáveis se não existirem
if 'df_dados' not in st.session_state:
    st.session_state.df_dados = pd.DataFrame()

# Estrutura inicial das regras (Baseada nos seus arquivos)
if 'db_mapeamento' not in st.session_state:
    st.session_state.db_mapeamento = pd.DataFrame([
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

if 'db_pesos_metro' not in st.session_state:
    st.session_state.db_pesos_metro = pd.DataFrame([
        {'secao': '50x20', 'peso_kg_m': 1.2638},
        {'secao': '25x25', 'peso_kg_m': 0.887},
        {'secao': '20x20', 'peso_kg_m': 0.7533},
        {'secao': '100x100', 'peso_kg_m': 6.275},
        {'secao': '50x50', 'peso_kg_m': 2.2691},
    ])

if 'db_pesos_conjunto' not in st.session_state:
    st.session_state.db_pesos_conjunto = pd.DataFrame([
        {'nome_conjunto': 'Leito metálico 920 Bate Forte', 'peso_unit_kg': 2.5},
        {'nome_conjunto': 'Pé Condutor 330 para mesas com estrutura metálica', 'peso_unit_kg': 12.0},
    ])

# --- 2. FUNÇÕES AUXILIARES ---
def carregar_excel_regras(uploaded_file):
    try:
        xls = pd.ExcelFile(uploaded_file)
        if 'MAPEAMENTO_TIPO' in xls.sheet_names:
            st.session_state.db_mapeamento = pd.read_excel(xls, 'MAPEAMENTO_TIPO')
        if 'PESO_POR_METRO' in xls.sheet_names:
            st.session_state.db_pesos_metro = pd.read_excel(xls, 'PESO_POR_METRO')
        if 'PESO_CONJUNTO' in xls.sheet_names:
            st.session_state.db_pesos_conjunto = pd.read_excel(xls, 'PESO_CONJUNTO')
        st.success("Base de dados atualizada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")

def gerar_excel_base():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        st.session_state.db_mapeamento.to_excel(writer, sheet_name='MAPEAMENTO_TIPO', index=False)
        st.session_state.db_pesos_metro.to_excel(writer, sheet_name='PESO_POR_METRO', index=False)
        st.session_state.db_pesos_conjunto.to_excel(writer, sheet_name='PESO_CONJUNTO', index=False)
        # Aba extra de parametros
        pd.DataFrame([{'parametro': 'densidade_aco', 'valor': 7.85}]).to_excel(writer, sheet_name='PARAMETROS', index=False)
    return output.getvalue()

# --- 3. MOTOR DE CÁLCULO ---
def calcular_final(df_input):
    # Converte DataFrames de configuração para Dicionários (para ficar rápido)
    map_rules = st.session_state.db_mapeamento.to_dict('records')
    
    # Cria dicionário { '50x50': 2.26, ... }
    dict_metro = dict(zip(st.session_state.db_pesos_metro['secao'], st.session_state.db_pesos_metro['peso_kg_m']))
    
    # Cria dicionário { 'Nome Peça': 12.0, ... }
    dict_conjunto = dict(zip(st.session_state.db_pesos_conjunto['nome_conjunto'], st.session_state.db_pesos_conjunto['peso_unit_kg']))
    
    densidade = 7.85
    
    resultados = []
    
    for _, row in df_input.iterrows():
        desc = str(row['DESCRIÇÃO'])
        qtd = float(row['QTD']) if row['QTD'] else 0.0
        
        # 1. Identificação
        tipo_final = "DESCONHECIDO"
        for regra in map_rules:
            if str(regra['texto_contido']).upper() in desc.upper():
                tipo_final = regra['tipo']
                break
        
        # Fallbacks
        if tipo_final == "DESCONHECIDO":
            if "TUBO" in desc.upper(): tipo_final = "tubo GENERICO"
            elif "CHAPA" in desc.upper(): tipo_final = "CH_PLANA"

        # 2. Cálculo
        peso_unit = 0.0
        metodo = "-"
        
        # Tenta extrair medida mm
        medida_mm = 0.0
        try:
            txt = str(row['MEDIDA']).lower().replace('mm','').strip()
            medida_mm = float(txt) if txt else 0.0
        except: pass

        # Regra: CONJUNTO
        if tipo_final == 'CONJUNTO':
            # Busca nome parcial
            for nome, peso in dict_conjunto.items():
                if nome.upper() in desc.upper():
                    peso_unit = peso
                    metodo = "Tabela (Conjunto)"
                    break
        
        # Regra: TUBO
        elif 'tubo' in tipo_final.lower():
            secao = tipo_final.lower().replace('tubo ', '').strip() # ex: "50x50"
            if secao == "generico":
                busca = re.search(r'(\d+x\d+)', desc)
                if busca: secao = busca.group(1)
            
            peso_m = dict_metro.get(secao, 0.0)
            if peso_m > 0 and medida_mm > 0:
                peso_unit = (medida_mm/1000) * peso_m
                metodo = f"Linear ({secao})"
        
        # Regra: CHAPA
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


# --- 4. INTERFACE VISUAL (ABAS) ---
st.title("🏭 Metalurgia System 3.0")

aba_calc, aba_db = st.tabs(["📋 Calculadora de Pedidos", "🛠️ Editor da Base de Dados"])

# === ABA 1: CALCULADORA ===
with aba_calc:
    col_up, col_btn = st.columns([3, 1])
    with col_up:
        uploaded_pdf = st.file_uploader("Suba o Relatório PDF do Pedido", type="pdf")
    
    # Processamento do PDF
    if uploaded_pdf:
        # Se for um arquivo novo (diferente do anterior), reprocessa
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

    # Editor do Pedido Atual
    if not st.session_state.df_dados.empty:
        st.markdown("### 1. Verifique o Pedido")
        df_editado = st.data_editor(
            st.session_state.df_dados,
            num_rows="dynamic",
            use_container_width=True,
            key="editor_pedido"
        )
        
        if st.button("🚀 Calcular Pesos Agora", type="primary"):
            df_res = calcular_final(df_editado)
            
            st.markdown("---")
            total = df_res['PESO_TOTAL'].sum()
            c1, c2 = st.columns(2)
            c1.metric("Peso Total", f"{total:.2f} kg")
            c2.metric("Itens", len(df_res))
            
            st.dataframe(df_res, use_container_width=True)
            
            # Download Resultado
            buffer_res = io.BytesIO()
            with pd.ExcelWriter(buffer_res, engine='openpyxl') as writer:
                df_res.to_excel(writer, index=False)
            
            st.download_button("📥 Baixar Planilha de Pesos", buffer_res.getvalue(), "Resultado_Calculo.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        if st.button("Limpar Pedido"):
            st.session_state.df_dados = pd.DataFrame()
            st.rerun()

# === ABA 2: EDITOR DA BASE DE DADOS ===
with aba_db:
    st.header("Gerenciar Regras de Cálculo")
    st.markdown("Aqui você edita a inteligência do sistema. Todas as alterações são salvas instantaneamente para os próximos cálculos.")
    
    col_import, col_export = st.columns(2)
    with col_import:
        up_db = st.file_uploader("Importar Base Excel (Sobrescreve tudo)", type="xlsx")
        if up_db:
            carregar_excel_regras(up_db)
            
    with col_export:
        st.write("Salvar Base Atualizada:")
        excel_data = gerar_excel_base()
        st.download_button("💾 Baixar Base_Calculo_Final.xlsx", excel_data, "Base_Calculo_Peso_Metalurgia_FINAL.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    st.markdown("---")
    
    # Editores das Tabelas de Regra
    tab1, tab2, tab3 = st.tabs(["🔀 Mapeamento de Tipos", "⚖️ Pesos por Metro (Tubos)", "📦 Pesos de Conjuntos"])
    
    with tab1:
        st.caption("Se a 'DESCRIÇÃO' do PDF contiver o texto da esquerda, o sistema assume o tipo da direita.")
        st.session_state.db_mapeamento = st.data_editor(st.session_state.db_mapeamento, num_rows="dynamic", use_container_width=True, key="edit_map")
        
    with tab2:
        st.caption("Tabela de peso linear (kg/m) para tubos e perfis.")
        st.session_state.db_pesos_metro = st.data_editor(st.session_state.db_pesos_metro, num_rows="dynamic", use_container_width=True, key="edit_metro")
        
    with tab3:
        st.caption("Itens que não usam medida linear, mas têm peso fixo unitário.")
        st.session_state.db_pesos_conjunto = st.data_editor(st.session_state.db_pesos_conjunto, num_rows="dynamic", use_container_width=True, key="edit_conj")