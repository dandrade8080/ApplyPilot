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
- **Automação:** Patchright 1.60.1 (fork do Playwright com stealth)
- **LLM:** DeepSeek-chat (único provider configurado)
- **Banco:** SQLite (applypilot.db)
- **Perfil persistente:** Chrome profile em ~/.applypilot/patchright_profile/
- **SO:** Windows 11 (PowerShell 5.1)

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

### 3. Aplicação (Engine Patchright)
- `src/applypilot/apply/engine.py` — motor principal de automação
- `src/applypilot/apply/form_detector.py` — detecta tipo de ATS e campos de formulário
- `src/applypilot/apply/field_matcher.py` — mapeia labels de campos para profile (~130 padrões)
- `src/applypilot/apply/question_answering.py` — responde perguntas de triagem via LLM

### Fluxo do Motor (apply_to_job)
1. Launch browser (persistent profile, stealth args)
2. Navigate to job URL
3. Detect form type (linkedin, gupy, indeed, greenhouse, lever, workday, etc.)
4. Route to specific handler:
   - `_handle_linkedin_easy_apply` — LinkedIn (inline modal + external redirect)
   - `_handle_gupy` — Gupy (login + curriculum form)
   - `_handle_indeed_apply` — Indeed (inline + external)
   - `_handle_generic_apply` — qualquer outro ATS (fallback)
5. Each handler: find apply button, fill form fields, submit

### Estrutura de Arquivos
```
src/applypilot/
├── apply/
│   ├── engine.py          # Motor Patchright (launcher, handlers, field filling)
│   ├── form_detector.py   # Detecção de ATS, campos, botões
│   ├── field_matcher.py   # Mapeamento label → campo do profile
│   ├── question_answering.py  # LLM para perguntas de triagem
│   └── chrome.py          # Chrome manager original (legado, pré-apply)
├── cli.py                 # CLI (com --provider patchright)
├── discovery/             # Busca de vagas
├── scoring/               # Pontuação e tailoring
│   ├── tailor.py          # Criação de currículo específico (português)
│   ├── cover_letter.py    # Geração de carta de apresentação (português)
│   └── validator.py       # Regras de validação (REQUIRED_SECTIONS em português)
├── llm.py                 # Cliente LLM (DeepSeek)
└── config.py              # Configurações (caminhos, APP_DIR)
```

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

### Decisão 3: Modo Totalmente Automático
- **Problema:** Modo híbrido (pausar para login manual) não atende objetivo de autonomia
- **Solução:** Depurar ATS por ATS para suporte 100% automático
- **Status:** Em andamento

### Decisão 4: Profile.json expandido
- **Problema:** Profile original (~80 linhas) não cobria campos dos formulários
- **Solução:** Expandir para ~200 linhas com seções: skills_boundary, projetos, educacao_completa, realizacoes, certificacoes, respostas_padrao, about_resumo, ats_credentials
- **Status:** Implementado

### Decisão 5: LinkedIn Easy Apply via Generic Handler
- **Problema:** LinkedIn Easy Apply inline modal usa React com estrutura diferente de Gupy — campos sem `name`, radios sem `name`, texto com label
- **Solução:** Delegar todo o fluxo ao `_handle_generic_apply` em vez de criar handler específico. As melhorias (radio grouping, _fill_field_by_label, multi-step) resolveram a maioria dos problemas.
- **Status:** Quase lá — bug do `va`/varejista corrigido, precisa testar

### Decisão 6: Regex SEMPRE usar \b para patterns curtos
- **Problema:** Pattern `vt|va|vr` casava com substrings dentro de palavras (ex: "va" em "varejista")
- **Solução:** Sempre usar `\b` (word boundary) em alternativas de 2-3 caracteres em FIELD_PATTERNS
- **Impacto:** Impede que patterns de benefícios interfiram em labels de experiência/educação

## Estado Atual (04/06/2026 — Web App Phase)

### Novo: Web Application (Flask)
- ✅ Interface web em http://127.0.0.1:5000/ com Flask
- ✅ Dashboard com pipeline progress, score distribution, jobs by source
- ✅ Profile viewer + editor (formulário web)
- ✅ Pipeline controls via web (run, cancel, status monitoring)
- ✅ Apply Queue: enqueue, batch enqueue (by min_score), process, cancel, clear
- ✅ Knowledge Base: CRUD completo via API + web UI
- ✅ Alerts: pending questions, answer/dismiss flow, knowledge auto-save
- ✅ Single job apply via web API

### Novo: Knowledge Base (QA Memory)
- ✅ `knowledge.py` — Persistent Q&A memory with keyword similarity search
- ✅ `save_knowledge()` — deduplicates similar questions (>70% overlap), tracks usage
- ✅ `find_answer()` — returns best match with confidence; auto-increments used_count
- ✅ Confidence scoring: LLM returns confidence 0.0-1.0, stored per entry
- ✅ Context tags for future filtering

### Novo: Alert System
- ✅ `alerts.py` — creates alerts when LLM confidence < 60%
- ✅ `answer_alert()` — user answers pending question + auto-saves to knowledge base
- ✅ `dismiss_alert()` — discard without answering
- ✅ Status tracking: pending → answered/dismissed

### Novo: Apply Queue
- ✅ `apply_queue.py` — batch application queue with status transitions
- ✅ `enqueue_job()` — adds with dedup (prevents double-queuing)
- ✅ `dequeue_next()` — atomic dequeue with status → processing
- ✅ `complete_queue_entry()` — marks completed/failed with result dict
- ✅ Background worker thread processed via `/api/apply-queue/process`
- ✅ Full CRUD via API: enqueue, batch enqueue, cancel, clear, status

### Funcionando
- ✅ Descoberta de vagas (368 jobs totais no DB)
- ✅ Scoring + Tailoring + Cover letters (22 jobs com score ≥ 7, tailored e cover letter)
- ✅ CLI com --provider patchright
- ✅ Launch browser com stealth args (--start-maximized, viewport fixo, disable-automation)
- ✅ LinkedIn login (sessão persistente)
- ✅ Gupy auto-login + overlay dismiss + form fill (wescale e grupomarquise)
- ✅ LinkedIn Easy Apply field detection (modal-scoped, sem falsos campos)
- ✅ LLM DeepSeek respondendo screening questions em tempo real
- ✅ Multi-step form handling (radio grouping, _fill_field_by_label, campo sem name/id)
- ✅ **`_verify_submitted(page, form_type)`** — verificação platform-specific de confirmação
- ✅ Screenshots salvos em `~/.applypilot/screenshots/` para debug
- ✅ _find_submit com busca modal-scoped + fallback full-page com patterns restritos
- ✅ `_fill_field_by_label`: preenche campos sem name/id via JS label lookup + nativeSetter + synthetic events
- ✅ `extractGroupLabel` melhorado: FIELDSET/legend, own text, sibling text, exclui option labels (Sim/Não)
- ✅ `find_all_apply_buttons` retorna `href` + filtra por viewport (elementos visíveis apenas)
- ✅ Generic handler scrolls into view antes de clicar
- ✅ Radio grouping: nameless radios usam `group_label` como fallback; "already checked" conta como filled
- ✅ Submeter botão: padrões expandidos com `avançar|avanç`
- ✅ Multi-step: após submit, detecta próximos campos direto (skip wait_for_new_fields), reset previous_count=0
- ✅ YES_NO_LABELS expandido: `trabalharia.*presencial|presencialmente` → "yes"
- ✅ Profile pattern expandido: `anos.*(?:experiência|experiencia|exp)` adicionado (era só inglês `years.*`)
- ✅ `_dismiss_overlays` reescrito em JS nativo com polling 30s; fallback navega direto pra `/curriculum`
- ✅ **`_SCAN_FORM_JS` agora aceita container_selector** — escaneia apenas DENTRO do modal LinkedIn, ignorando barra de pesquisa global, seletor de idioma, etc.
- ✅ **`llm_client = get_client()`** — LLM DeepSeek inicializado e respondendo perguntas de triagem em tempo real
- ✅ **`answer_screening_question` importado em `_handle_generic_apply`** — corrigido NameError

### Bugs Corrigidos (04/06/2026)

#### Manhã

**Bug 1: `va` em `varejista`**
- **Problema:** Pattern `vt|va|vr` casava com "va" dentro de "varejista"
- **Correção:** `\bvt\b|\bva\b|\bvr\b` em `field_matcher.py:79`

**Bug 2: `llm_client = None` (engine.py:216)**
- **Problema:** LLM nunca inicializado, perguntas de triagem não respondidas
- **Correção:** `llm_client = get_client()` em vez de `None`

**Bug 3: `answer_screening_question` não importado em `_handle_generic_apply`**
- **Problema:** NameError ao chamar `answer_screening_question` dentro do handler genérico
- **Correção:** Import adicionado dentro da função

**Bug 4: LinkedIn detectando campos falsos (Pesquisar, idioma, etc.)**
- **Problema:** `_SCAN_FORM_JS` varria a página INTEIRA, pegando a barra de pesquisa global do LinkedIn (`aria-label="Pesquisar"`), seletor de idioma no footer, etc. Isso causava:
  - Preenchimento de texto enorme no campo de busca
  - Loop infinito (mesmos campos reapareciam após submit)
  - Nunca chegava ao review/submit
- **Causa:** Nenhum escopo de container — todos `input`/`select` da página eram detectados
- **Correção:**
  1. `_SCAN_FORM_JS` aceita `containerSelector` para escopar a busca
  2. `detect_form_fields(page, container_selector)` propaga o seletor
  3. `detect_linkedin_modal_fields(page)` busca modals conhecidos (`.jobs-easy-apply-modal`, `.artdeco-modal--layer-fixed`, `[data-test-modal]`)
  4. `NON_FORM_SELECTORS` no JS exclui: `#global-nav-search`, `input[aria-label*="Pesquisar"]`, `footer select/input`, etc.
  5. Se um modal existe, elementos FORA dele são automaticamente excluídos
  6. `_handle_generic_apply` usa funções auxiliares `_detect()`, `_find_submit()`, `_wait_fields()` que automaticamente escopam ao container quando `form_type == "linkedin_easy_apply"`
- **Arquivos:** `form_detector.py`, `engine.py`

**Bug 5: `_check_success` e "0 visible fields = applied" — FALSO POSITIVO**
- **Problema:** O sistema marcava candidaturas como "applied" sem realmente ter submetido:
  1. `_check_success` buscava palavras soltas no body todo (ex: "obrigado" no footer, "recebemos" em texto qualquer) → falso positivo
  2. "0 visible fields após submit" era interpretado como sucesso imediato, sem verificar confirmação real
  3. LinkedIn: após step 3 (screening), não encontrava botão de submit ("Revisar"/"Enviar") e caía no `_check_success` que retornava True por achar "obrigado" em algum lugar da página
  4. Gupy: após submit, 0 visible fields era detectado antes da página de confirmação carregar
- **Impacto:** 4 jobs marcados como applied que NÃO foram submetidos (usuário confirmou que não recebeu emails)
- **Correção:**
  1. Substituído `_check_success` por `_verify_submitted(page, form_type)` com verificações platform-specific:
     - **LinkedIn**: procura `.jobs-easy-apply-modal` com texto "candidatura enviada", `.artdeco-modal--confirm`, ou botão "Applied"
     - **Gupy**: procura URL com "/success" ou texto "candidatura enviada com sucesso"
     - **Indeed**: procura "candidatura enviada" ou "application sent"
     - **Generic**: busca padrões específicos (não mais palavras isoladas)
  2. "0 visible fields" agora chama `_verify_submitted` primeiro, espera 3s extra se ainda 0 fields, e só retorna "applied" se confirmado
  3. LinkedIn "no submit button" agora faz busca ampla (full-page fallback + patterns "revisar"/"review"/"enviar"/"submit") antes de desistir
  4. Screenshot capturado em caso de falha para debug
- **Polling:** até 8 segundos com verificações a cada 1s para cada plataforma
- **Arquivo:** `engine.py` — função `_verify_submitted()`
- **Verificação:** Dry-run mostra `_verify_submitted` retornando `false` nos steps intermediários (correto!), não mais falso positivo

#### Tarde

**Bug 6: Gupy loop infinito — steps não incrementado após 0 visible fields**
- **Problema:** Após clicar "salvar e continuar" no step 0 do Gupy, os campos sumiam (0 visible). O código executava `continue` sem incrementar `steps`, reprocessando os mesmos 5 campos obsoletos a cada iteração. Após 3 tentativas sem submit button (já clicado), caía em `could_not_complete`.
- **Correção:** `steps += 1` e `previous_count = 0` antes do `continue`. Também adicionado polling de 5s para submit button na página pós-step (review page).
- **Arquivo:** `engine.py:703-711`

**Bug 7: LinkedIn/Salvar vaga — full-page fallback achava botão fora do modal**
- **Problema:** `_find_submit` com container-scope retornava null, então o fallback full-page (`find_submit_button(page, None)`) achava "Salvar vaga" no sidebar do LinkedIn (match com pattern `/salvar/i`) ou "Enviar mensagem" no perfil do recrutador (match `/enviar/i`). Clicar nesses botões não avançava o formulário e às vezes navegava para fora do modal.
- **Correção:** `_find_submit` agora faz busca tripla:
  1. Container-scoped (padrão)
  2. Broad modal-scoped (mais patterns, mais seletores) — se container existe
  3. Full-page APENAS com patterns de submit final (`/enviar|submit|concluir|finalizar|candidatar|send/i`) — exclui "salvar", "avançar", "continuar"
- **Arquivo:** `engine.py:499-530`

**Bug 8: Indeed inline handler retornava "applied" sem verificação**
- **Problema:** `_handle_indeed_apply` linha 461-462 retornava `{"status": "applied"}` imediatamente ao clicar botão com padrão `submit|enviar|concluir|finalizar`, sem verificar confirmação real.
- **Correção:** Substituído por `_verify_submitted(page, "indeed")` com polling de 5+3s. Apenas dry-run recebe "benefit of doubt"; execução real retorna `failed` se não confirmar.
- **Arquivo:** `engine.py:461-468`

**Melhoria: Patterns de submit button agora incluem `/candidatar/i`**
- **Problema:** Gupy review page tem botão "Candidatar-se" que não era detectado por `_FIND_SUBMIT_BUTTON_JS`
- **Correção:** Adicionado `/candidatar/i` aos patterns
- **Arquivo:** `form_detector.py:376`

**Melhoria: Screenshots agora salvos em arquivo**
- **Problema:** `page.screenshot()` era chamado mas o resultado (bytes) era descartado — sem utilidade para debug
- **Correção:** Salvo em `~/.applypilot/screenshots/fail_{title}_{timestamp}.png`
- **Arquivo:** `engine.py:730-738`

### Problemas Conhecidos
1. ~~**Gupy React forms** — RESOLVIDO.~~
2. ~~**LinkedIn Easy Apply** — RESOLVIDO (modal-scoped field detection + LLM client).~~
3. ~~**Falso positivo "applied" sem confirmação** — RESOLVIDO (`_verify_submitted`).~~
4. **LinkedIn Talent Widget** — Tetra Pak usa iframe cross-origin do LinkedIn. Inacessível por JS.
5. **Workday** — Handler específico não implementado
6. **Greenhouse** — Handler específico não implementado
7. **Lever** — Handler específico não implementado
8. **Amazon Jobs** — Indeed redirects para amazon.jobs encontram tela de login sem submit button detectável
9. **Indeed → ATS externo** — Cada Indeed job redireciona para um ATS diferente (Gupy ✅, Amazon ❌, InfoJobs ❌)
10. **Gupy pós-questions** — Após step 0 de perguntas, Gupy redireciona para `/curriculum` com body ~800 chars e sem botão de submit. Fluxo não finaliza.
11. **LinkedIn Easy Apply não-detetado em visitas repetidas** — Após múltiplas tentativas no mesmo job, LinkedIn pode ocultar "Candidatura simplificada" e mostrar "Enviar mensagem". Cleanup de sessão necessário.
12. **Select fields lentos** — `page.select_option` com label textual (ex: "Brasil") pode levar minutos se o valor não casar com as options. Precisa de fallback para selecionar por texto visível.

### Jobs Restantes
22 jobs com tailored resume, dos quais:
- **Permanentemente bloqueados (Indeed sem handler):** ~5 jobs (Head de Marketing, Product Marketing/Payments, etc.)
- **LinkedIn com Easy Apply:** ~6 jobs (testar com sessão limpa)
- **LinkedIn externo (InfoJobs/Pandape):** 2 jobs (não suportado)
- **Gupy:** 4 jobs (wescale, cortex, aprovadigital — fluxo de perguntas não finaliza)
- **Marquise/LinkedIn:** 1 job (Coordenador Marketing Digital — Gupy pipeline completo testado, pode funcionar)

## Próximos Passos
1. **Testar fluxo completo via web UI**: discover → enrich → score → tailor → enqueue → apply
2. **Debug Gupy pós-questions** — verificar se `/curriculum` com 800 chars é página de sucesso camuflada ou erro de loading
3. **Corrigir select lento** — `_fill_field` para selects: tentar `select_option` por label em vez de value apenas
4. **Limpar/rotacionar perfil Chrome** para evitar que LinkedIn memorize estado de aplicações anteriores
5. **Agendar descoberta + apply** em lote noturno
6. **SSE/polling endpoint** para status em tempo real no dashboard
7. **Responsividade mobile** dos templates web

## Arquivos Relevantes
- `C:\Users\dandr\.applypilot\profile.json` — Perfil expandido + ats_credentials
- `C:\Users\dandr\.applypilot\searches.yaml` — Filtros de busca
- `C:\Users\dandr\.applypilot\applypilot.db` — Banco SQLite (368 jobs)
- `C:\Users\dandr\.applypilot\patchright_profile\` — Perfil Chrome persistente
- `C:\Users\dandr\.applypilot\screenshots\` — Screenshots de falhas
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\apply\engine.py` — Motor principal
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\apply\form_detector.py` — Detector de formulários
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\apply\field_matcher.py` — Mapeamento de campos
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\apply\question_answering.py` — Respostas LLM (+ KB lookup)
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\knowledge.py` — QA memory (busca por similaridade)
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\alerts.py` — Sistema de alertas
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\apply_queue.py` — Fila de apply em lote
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\web\routes.py` — Flask routes (31 endpoints)
- `C:\Users\dandr\ApplyPilot\ApplyPilot\src\applypilot\web\templates\` — 11 templates HTML
- `C:\Users\dandr\ApplyPilot\ApplyPilot\PLANO_REFATORACAO.md` — Plano de 7 fases

## Nova Stack Web
```
src/applypilot/web/
├── __init__.py        # Flask app factory
├── routes.py          # 31 rotas (HTML pages + JSON API)
├── linkedin.py        # LinkedIn profile scraper
└── templates/
    ├── base.html          # Layout sidebar + nav (atualizado: Queue, Knowledge, Alerts)
    ├── dashboard.html     # Pipeline overview
    ├── jobs.html          # Job list by stage
    ├── job_detail.html    # Single job view
    ├── profile.html       # Profile viewer
    ├── profile_edit.html  # Profile editor
    ├── pipeline.html      # Pipeline controls (run/cancel + status)
    ├── config.html        # Config viewer
    ├── apply_queue.html   # Queue management
    ├── knowledge.html     # Q&A memory CRUD
    └── alerts.html        # Pending questions
```

## Comandos Úteis
```bash
# Aplicar para vagas (provider patchright)
python -m applypilot apply --limit 3 --provider patchright

# Dry run (não envia, só testa)
python -m applypilot apply --dry-run --provider patchright

# Job específico (LinkedIn)
python -m applypilot apply --provider patchright --url "https://www.linkedin.com/jobs/view/4418395939"

# Marcar job como applied manualmente
python -m applypilot apply --mark-applied "URL_DO_JOB"

# Resetar jobs com falha
python -m applypilot apply --reset-failed

# Status do pipeline
python -m applypilot status

# Ver screenshot mais recente
Get-ChildItem -Path "$env:USERPROFILE\.applypilot\screenshots\*.png" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# Servidor web (http://127.0.0.1:5000/)
python -m applypilot web

# Aplicar para vaga específica via API
curl -X POST http://127.0.0.1:5000/api/jobs/apply -H "Content-Type: application/json" -d "{\"url\":\"URL_AQUI\"}"

# Enfileirar lote via API
curl -X POST http://127.0.0.1:5000/api/apply-queue/enqueue-batch -H "Content-Type: application/json" -d "{\"min_score\":7,\"limit\":10}"

# Processar fila via API
curl -X POST http://127.0.0.1:5000/api/apply-queue/process -H "Content-Type: application/json" -d "{\"max_jobs\":3}"
```
```
