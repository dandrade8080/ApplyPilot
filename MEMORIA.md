# ApplyPilot - Memória do Projeto

## Objetivo Principal
Sistema autônomo de candidatura a vagas de emprego que:
1. Busca oportunidades por filtro do usuário
2. Pontua similaridade com perfil do candidato
3. Seleciona vagas acima de threshold configurável
4. Cria currículo específico por vaga
5. Usa cover letter única fornecida pelo usuário
6. Candidata-se automaticamente às vagas selecionadas

## Stack Tecnológica
- **Linguagem:** Python 3.12+
- **Automação:** Patchright 1.60.1 (fork do Playwright com stealth) + **browser-use 0.12.9** (AI agent)
- **LLM:** DeepSeek-chat (via LangChain ChatOpenAI)
- **Banco:** SQLite (applypilot.db)
- **Perfil persistente:** Chrome profile em ~/.applypilot/patchright_profile/
- **SO:** Windows 11 (PowerShell 5.1)
- **Servidor web:** Flask (http://127.0.0.1:5000)

## Usuário
- Nome: Daniel Andrade
- Email: dandrade80@gmail.com
- Localização: São Paulo, SP
- LinkedIn: (configurado no profile.json)
- Gupy: dandrade80@gmail.com / Senha2*0

## Filtros de Busca (searches.yaml)
- Idioma: Português Brasileiro
- Excluir "Growth" do título
- Aceitar: Head de/Head of/Gerente de/Coordenador de/Diretor de/Marketing Manager/Marketing Director
- Local: São Paulo (presencial) + SP metro area + remote/híbrido
- Excluir: Rio de Janeiro/RJ, US, Canada, Europe, India, Australia, London
- Excluir cargos: estágio, trainee, junior, analista, pleno, supervisor, assistente, auxiliar, Jovem Aprendiz, estagiário, consultor, growth
- Sites: LinkedIn, Indeed (Glassdoor retorna 400)
- Resultados: 30/site | Janela: 7 dias

## Arquitetura do Sistema

### 1. Descoberta (Discovery)
- `src/applypilot/discovery/` — busca vagas nos sites configurados
- Lê filtros de `searches.yaml`
- Armazena resultados no SQLite (tabela `jobs`)

### 2. Scoring (Pontuação)
- `src/applypilot/scoring/` — avalia similaridade com perfil
- LLM (DeepSeek-chat) compara descrição da vaga com perfil
- Gera fit_score (0-10) e score_reasoning
- Tailoring: cria currículo específico por vaga (Portuguese prompts)
- Cover letter: geração por vaga (substituível por arquivo único)

### 3. Aplicação
- **PRIMÁRIO: `ai_apply.py`** — browser-use + DeepSeek via LangChain. AI Agent navega, entende o formulário visualmente, preenche campos, faz upload, responde perguntas, e submete. Funciona em qualquer ATS.
- **FALLBACK: `engine.py`** — método heurístico original (regex + JS scanning). Usado se browser-use falhar.

### Estrutura de Arquivos
```
src/applypilot/
├── apply/
│   ├── engine.py             # Motor original (launcher, handlers, field filling) + fallback
│   ├── ai_apply.py           # NOVO: browser-use Agent com DeepSeek (método primário)
│   ├── form_detector.py      # Detecção de ATS, campos, botões
│   ├── field_matcher.py      # Mapeamento label → campo do profile (~130 padrões)
│   ├── question_answering.py # LLM para perguntas de triagem (+ KB lookup)
│   ├── deepseek_agent.py     # Agente DeepSeek original (legado)
│   └── chrome.py             # Chrome manager original (legado)
├── web/
│   ├── __init__.py           # Flask app factory
│   ├── routes.py             # 34 rotas (HTML + JSON API)
│   ├── linkedin.py           # LinkedIn profile scraper
│   └── templates/            # 12 templates HTML
├── cli.py                    # CLI com comando `serve`
├── discovery/                # Busca de vagas
├── scoring/                  # Pontuação e tailoring
│   ├── tailor.py             # Criação de currículo específico (português)
│   ├── cover_letter.py       # Geração de carta de apresentação (português)
│   └── validator.py          # Regras de validação
├── knowledge.py              # QA memory (busca por similaridade)
├── alerts.py                 # Sistema de alertas (perguntas não respondidas)
├── apply_queue.py            # Fila de apply em lote
├── llm.py                    # Cliente LLM unificado (DeepSeek)
├── database.py               # SQLite thread-local connections
└── config.py                 # Configurações (caminhos, APP_DIR, load_env)
```

## Status do Banco de Dados (04/06/2026)
- **Total jobs:** 585
- **Scored:** 585 (100%)
- **Tailored:** 20
- **Com cover letter:** 20
- **Ready to apply:** 16
- **Apply queue:** 14 (queued), 10 (failed — resetados)
- **Pending alerts:** 0
- **Knowledge entries:** 3

## Integração browser-use

### Como funciona
1. `apply_to_job()` tenta `apply_with_ai()` primeiro (via `ai_apply.py`)
2. Se falhar, cai no `_legacy_apply_to_job()` (engine.py)
3. `apply_with_ai()` cria um Agent browser-use com:
   - **Browser:** Chrome persistente (patchright_profile)
   - **LLM:** DeepSeek-chat via LangChain ChatOpenAI (patched com `provider` field)
   - **Task:** Descrição em português com dados do perfil, currículo, carta
4. O Agent navega, analisa a página com IA, preenche formulário, faz uploads, responde perguntas, submete

### Limitações atuais
- DeepSeek não suporta `use_vision=True` (browser-use desliga automaticamente)
- browser-use cria browser próprio (não reusa contexto do engine.py)
- Async: `asyncio.run()` em thread separada

### Dependências adicionais
- `browser-use==0.12.9`
- `langchain-openai`
- `pydantic-settings`

## Histórico de Decisões

### Decisão 1: Patchright em vez de LLM Agent
- **Problema:** Agente DeepSeek era instável, >100 chamadas de API por vaga, crashes frequentes
- **Solução:** Substituir por automação Patchright + LLM só para perguntas de triagem
- **Data:** Fase 3 do plano de refatoração

### Decisão 2: Perfil Persistente
- **Problema:** Clonar perfil Chrome a cada execução era lento e perdia sessões
- **Solução:** Usar `launch_persistent_context` com diretório fixo
- **Local:** ~/.applypilot/patchright_profile/
- **Benefício:** Login LinkedIn e Gupy persistem entre execuções

### Decisão 3: browser-use como método primário de apply
- **Problema:** Regex/heurística não funciona em todos os ATS (Greenhouse, Workday, Ashby, etc.)
- **Solução:** browser-use entende o formulário com IA, sem padrões hardcoded
- **Status:** Implementado, aguardando teste com vaga real

### Decisão 4: Sincronização com GitHub
- A partir de 04/06/2026, todo commit é push automático para `origin main`
- Repositório: https://github.com/dandrade8080/ApplyPilot

## Bugs Corrigidos (04/06/2026 — Sessão Tarde/Noite)

### Bug 9: `_find_submit` não definido (NameError)
- **Problema:** Função `_find_submit` encapsulada dentro de `_handle_generic_apply` não era acessível por handlers externos (LinkedIn, Indeed)
- **Correção:** Extraída para função de módulo `_find_submit_button(page, container=None)` em `engine.py`
- **Arquivo:** `engine.py`

### Bug 10: Chrome não iniciava (perfil travado por processos zombies)
- **Problema:** `launch_persistent_context` falhava porque processos Chrome de sessões anteriores ficavam presos
- **Correção:** `_kill_zombie_chrome()` mata apenas processos com `patchright_profile` ou `no-first-run` no cmdline
- **Reforço:** `close_browser()` também limpa processos residuais

### Bug 11: `launch_browser()` com taskkill matava Chrome do usuário
- **Problema:** Correção anterior usava `taskkill /F /IM chrome.exe` que matava TODOS os Chrome
- **Correção:** Substituído por `_kill_zombie_chrome()` que filtra por cmdline

## Problemas Conhecidos
1. **LinkedIn Talent Widget** — Tetra Pak usa iframe cross-origin do LinkedIn. Inacessível por JS.
2. **Workday** — Handler específico não implementado (engine legacy)
3. **Greenhouse** — Handler específico não implementado
4. **Lever** — Handler específico não implementado
5. **Indeed → ATS externo** — Cada Indeed job redireciona para um ATS diferente
6. **browser-use** `use_vision` desligado — DeepSeek não suporta; sem visão, depende de HTML/texto

## Próximos Passos
1. **Testar "Aplicar Prontas"** com browser-use em uma vaga real
2. Verificar se 5min timeout é suficiente para browser-use
3. Adicionar mais vagas à fila (via batch enqueue)
4. Monitorar erros de apply em tempo real

## Comandos Úteis
```bash
# Servidor web
serve

# Aplicar para vagas (via CLI)
python -m applypilot apply --limit 3 --provider patchright

# Dry run (não envia, só testa)
python -m applypilot apply --dry-run --provider patchright

# Status do pipeline
python -m applypilot status

# Ver screenshot mais recente
Get-ChildItem -Path "$env:USERPROFILE\.applypilot\screenshots\*.png" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# Resetar fila
python -c "from applypilot.database import get_connection; c=get_connection(); c.execute('UPDATE apply_queue SET status=\\'queued\\',error=NULL WHERE status=\\'failed\\''); c.commit()"

# Matar Chrome zombies (antes de aplicar)
Get-Process chrome | Where-Object { $_.Id -ne (Get-Process chrome | Select-Object -First 1).Id } | ForEach-Object { Stop-Process -Id $_.Id -Force }
```
