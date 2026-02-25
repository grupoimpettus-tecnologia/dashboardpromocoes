# 🎉 Dashboard de Promoções

Dashboard interativo para visualização de promoções das marcas **Bendito**, **Espetto** e **Mané** através da API do Degust.

## 📋 Características

- ✅ **Dados diretos da API** - Visualização em tempo real (sem arquivos Excel)
- ✅ **Todas as colunas** - Exibe todas as informações disponíveis na interface web
- ✅ **Nomes das lojas** - Mostra código e nome da loja (ex: "1 - DOWNTOWN")
- 🔄 **Botão de atualização** dos dados
- 🏷️ **Filtros por marca** (Bendito, Espetto, Mané)
- 📊 **Métricas detalhadas** - Total de promoções, colunas, lojas únicas, lojas com nome
- ⬇️ **Download CSV** por marca
- 🎨 **Interface moderna** e responsiva
- ⚡ **Cache inteligente** (5 minutos) para melhor performance
- 🔧 **Opções de exibição** - Filtre colunas específicas se desejar

## 🚀 Como Executar

### **Para NOVOS computadores (instalação automática):**

#### **Opção 1 - Instalação e Execução Automática (RECOMENDADA):**
```
Duplo clique no arquivo: INSTALAR_E_EXECUTAR.bat
```
*Este script verifica e instala automaticamente todas as dependências necessárias*

#### **Opção 2 - Dashboard Hierárquico:**
```
Duplo clique no arquivo: INSTALAR_E_EXECUTAR_HIERARQUICO.bat
```

#### **Opção 3 - Apenas Instalar Dependências:**
```
Duplo clique no arquivo: INSTALAR_DEPENDENCIAS.bat
```
*Depois execute um dos scripts de execução*

### **Para computadores com dependências já instaladas:**

#### **Opção 1 - Dashboard Normal:**
```
Duplo clique no arquivo: EXECUTAR_AGORA.bat
```

#### **Opção 2 - Dashboard Hierárquico:**
```
Duplo clique no arquivo: EXECUTAR_HIERARQUICO.bat
```

### **Via Python (manual):**
```bash
pip install -r requirements.txt
python -m streamlit run app_promocoes.py
```

### **Acessar no navegador:**
- Dashboard Normal: `http://localhost:8501`
- Dashboard Hierárquico: `http://localhost:8502`

## 📖 Como Usar

1. **Selecionar Marcas**: Use o menu lateral para escolher quais marcas deseja visualizar
2. **Atualizar Dados**: Clique no botão "🔄 Atualizar Dados" para buscar os dados mais recentes
3. **Visualizar TODAS as Colunas**: Agora todas as informações da API são exibidas na interface web
4. **Ver Nomes das Lojas**: Cada promoção mostra o código e nome da loja (ex: "1 - DOWNTOWN")
5. **Filtrar Colunas** (opcional): Use o expansor "🔧 Opções de Exibição" para escolher colunas específicas
6. **Download CSV**: Use os botões de download para exportar os dados em formato CSV
7. **Métricas Detalhadas**: Visualize total de promoções, colunas, lojas únicas e lojas com nome

## 🏪 Marcas Disponíveis

- **Promoções Bendito** (Código: 3082)
- **Promoções Espetto** (Código: 3078)
- **Promoções Mané** (Código: 1428)

## 🔧 Tecnologias Utilizadas

- **Streamlit**: Framework para criação de aplicações web em Python
- **Pandas**: Manipulação e análise de dados
- **Requests**: Comunicação com a API do Degust

## 🛠️ Solução de Problemas

### ❌ Erro: "No module named streamlit"

**Soluções em ordem de prioridade:**

1. **Instalar dependências:**
   ```
   Duplo clique em: INSTALAR_DEPENDENCIAS.bat
   ```

2. **Instalação e execução automática:**
   ```
   Duplo clique em: INSTALAR_E_EXECUTAR_HIERARQUICO.bat
   ```

3. **Reinstalação completa do Python:**
   ```
   Duplo clique em: REINSTALAR_PYTHON_COMPLETO.bat
   ```

### 🔧 Outros Problemas Comuns

- **Python não encontrado:** Reinstale o Python com "Add Python to PATH"
- **Porta em uso:** O sistema tentará usar porta alternativa automaticamente
- **Permissões:** Execute como administrador se necessário
- **Múltiplas instalações do Python:** Use o diagnóstico avançado para identificar conflitos

### 📋 Scripts Disponíveis

- `EXECUTAR_HIERARQUICO.bat` - **PRINCIPAL** - Executa o dashboard hierárquico
- `EXECUTAR_NORMAL.bat` - Executa o dashboard normal
- `INSTALAR_DEPENDENCIAS.bat` - Instala todas as dependências necessárias
- `INSTALAR_E_EXECUTAR_HIERARQUICO.bat` - Instala dependências e executa o dashboard hierárquico
- `REINSTALAR_PYTHON_COMPLETO.bat` - Instruções para reinstalação completa do Python

## 📝 Observações

- ✅ **Dados em tempo real** da API do Degust
- ✅ **Todas as colunas** exibidas na interface web
- ✅ **Cache inteligente** de 5 minutos para otimizar performance
- ✅ **Não gera arquivos Excel** localmente
- ✅ **Interface responsiva** e moderna
- ✅ **Scripts de diagnóstico** para resolver problemas automaticamente

