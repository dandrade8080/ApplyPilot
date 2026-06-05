# Plano de Refatoração — ApplyPilot

## Diagnóstico dos Problemas Atuais

### 1. Currículos com seções vazias (PROJETOS)
**Causa raiz**: O currículo base (`resume.txt`) não tem uma seção "Projetos" separada — os projetos (Mopar, New Holland, Odette.IA) estão embutidos dentro das descrições de experiência (ex: "Estratégia de comunicação e branding da Mopar em toda a América Latina" dentro de Stellantis).

O prompt de tailoring dá uma brecha: *"Se nenhum for relevante, use array vazio []"* — e o LLM usa essa brecha porque os projetos estão "escondidos" dentro das experiências.

Além disso, a validação trata `projects` vazio como **alerta**, não erro — então nunca pede retry.

**Correção necessária**: Extrair os projetos do currículo base para uma seção própria, ou mudar o prompt para instruir o LLM a extrair projetos das experiências.

### 2. FORMAÇÃO genérica
**Causa raiz**: O template JSON força `"education": "{school} | {education_level}"` — uma string única. O perfil do usuário tem 5 instituições com cursos, anos e certificações, mas só os nomes das escolas e "MBA Executivo" são passados ao LLM.

**Correção necessária**: Transformar `education` em array (como `experience`) no JSON template, e passar o histórico educacional completo no prompt.

### 3. DeepSeek não é confiável para browser agent
**Causa raiz**: O DeepSeek-chat não é bom em raciocínio visuo-espacial para navegação em formulários. Faz 100+ chamadas de API sem completar. O ApplyPilot original foi desenhado para Claude Code (que é muito superior nisso). Sem Claude, não temos um LLM bom o suficiente para o agente autônomo.

**Solucão**: Substituir a arquitetura de "agente LLM que decide cada ação" por um **sistema híbrido** com scripts de automação estruturados + LLM apenas para partes que exigem理解 semântica (ex: responder perguntas discursivas).

### 4. Perfil clonado não carrega sessões de login
**Causa raiz**: O sistema copia o profile do Chrome do usuário para um diretório worker. Esse processo é frágil — arquivos podem estar travados se o Chrome estiver aberto, e cookies de sessão podem não copiar corretamente.

**Solução**: Usar **cookie import** do Chrome em execução (como faz o ai-job-agent) em vez de clonar o perfil inteiro.

### 5. Sem anti-detecção
**Causa raiz**: O Playwright padrão é trivialmente detectável — `navigator.webdriver=true`, `HeadlessChrome` no user-agent, WebGL genérico, etc.

**Solução**: Substituir Playwright por **Patchright** (fork do Playwright com patches anti-detecção no nível CDP) e implementar comportamento humano (cliques com curva de Bézier, digitação com timing variável, delays aleatórios).

### 6. Sem base completa para responder perguntas
**Causa raiz**: O perfil do usuário atual é raso em dados comportamentais (resume_facts só tem 3 métricas, skills_boundary vazio, sem projetos cadastrados).

**Solução**: Expandir o perfil do usuário com dados completos de experiência, projetos, realizações, certificações — para que o LLM possa responder QUALQUER pergunta de triagem.

---

## Benchmarking de Soluções Existentes

### Projetos Open Source

| Projeto | Stars | Stack | Diferencial |
|---------|-------|-------|-------------|
| **ai-job-agent** (AkbarDevop) | 28 | Node.js + Playwright | Cookie import do Chrome, 228+ aplicações, auto-answer engine |
| **linkedin-auto-apply** (jtur671) | 1 | Next.js + Playwright | Fuzzy field matching, dashboard, profile audit |
| **AIJobHunter** (kertser) | 0 | Python + Playwright | LLM form filling, market intelligence, web GUI |
| **LangHire** (hamgor) | Novo | Python | Self-learning memory por ATS, desktop nativo |
| **AutoApply** (AbhishekMandapmalvi) | 3 | Python + Playwright | 6 ATS platforms (LinkedIn, Indeed, Greenhouse, Lever, Workday, Ashby) |
| **ApplyPilot** (Pickle-Pixel) | 874 | Python | **Este projeto** — original, AGPL-3.0 |

### Ferramentas Anti-Detecção

| Ferramenta | Tipo | Eficácia |
|------------|------|----------|
| **Patchright** (3.2k stars) | Fork do Playwright | Passa Cloudflare, DataDome, Akamai, Kasada |
| **Camoufox** | Fork do Firefox | Melhor para fingerprint de canvas/WebGL |
| **playwright-stealth** | Plugin | Desatualizado desde 2024, não funciona mais |
| **Browserless** | Serviço gerenciado | Pago, infraestrutura de browser remoto |

### Serviços Comerciais

| Serviço | Foco | Preço |
|---------|------|-------|
| **LinkedHelper** | Automação de vendas LinkedIn (não job apply) | ~$89-149/mês |
| **Resumly Autopilot** | Job apply automatizado | Pago, SaaS |
| **ZenRows** | Anti-bot scraping API | ~$50-500/mês |

---

## Plano de Implementação — 7 Fases

### Fase 1: Expandir Perfil do Usuário (base para tudo)

**O que**: Enriquecer `profile.json` com dados completos para o LLM responder perguntas de triagem.

**Arquivos**: `profile.json`

**Mudanças**:
- Preencher `skills_boundary` com habilidades reais (programação, frameworks, ferramentas, idiomas)
- Adicionar `projetos` como array com nome, descrição, tecnologias, resultados — extraindo do currículo base
- Adicionar `educacao_completa` com histórico completo (instituição, curso, ano, tipo)
- Adicionar `realizacoes` com lista de conquistas mensuráveis
- Adicionar `certificacoes` se houver
- Adicionar `preferencias_resposta` com respostas padrão para perguntas comuns (ex: "Why do you want to work here?", "Tell us about yourself")

**Tempo estimado**: 2-3 horas (preenchimento manual dos dados)

### Fase 2: Corrigir Geração de Currículos (PROJETOS e FORMAÇÃO)

**O que**: Ajustar o pipeline de tailoring para gerar seções completas.

**Arquivos**:
- `src/applypilot/scoring/tailor.py` — prompt + parser
- `src/applypilot/scoring/validator.py` — regras de validação

**Mudanças**:
1. No prompt de tailor, instruir o LLM a **extrair projetos das experiências** caso não haja seção separada
2. Mudar `education` de string para array no JSON template, com objetos `{institution, degree, year}`
3. Tornar `projects` vazio como **erro** (não warning) para forçar retry com feedback
4. Passar `educacao_completa` do perfil no contexto do prompt
5. Adicionar no prompt: "Se os projetos descritos nas experiências puderem ser extraídos, crie uma seção PROJETOS separada"

**Tempo estimado**: 4-6 horas

### Fase 3: Substituir DeepSeek Agent por Automação Estruturada

**O que**: Trocar a arquitetura de "LLM decide cada ação" por scripts de automação diretos.

**Arquivos**:
- `src/applypilot/apply/deepseek_agent.py` — substituir completamente
- `src/applypilot/apply/launcher.py` — modificar worker_loop
- `src/applypilot/apply/chrome.py` — modificar setup de perfil

**Mudanças**:
1. Substituir Playwright MCP por **Patchright** (`pip install patchright`)
2. Criar `src/applypilot/apply/engine.py` — motor de automação que:
   - Abre Chrome com perfil persistente (não clonado)
   - Detecta o tipo de formulário (LinkedIn Easy Apply, Greenhouse, Lever, etc.)
   - Usa um **form filler genérico** que identifica campos por label/frase/placeholder
   - Preenche campos com dados do perfil + currículo
   - Apenas usa LLM para perguntas discursivas (não para navegação)
3. Implementar **cookie import** do Chrome já aberto pelo usuário (em vez de clonar perfil)
4. Criar `src/applypilot/apply/form_detector.py` — detector de campos que mapeia labels do formulário para campos do perfil

**Tempo estimado**: 20-30 horas

### Fase 4: Implementar Anti-Detecção

**O que**: Tornar o browser invisível para Cloudflare e sistemas anti-bot.

**Arquivos**:
- `src/applypilot/apply/chrome.py` — config do Patchright
- `src/applypilot/apply/engine.py` — comportamento humano

**Mudanças**:
1. Substituir `playwright` por `patchright` na inicialização do Chrome
2. Configurar Patchright com perfil persistente:
   ```python
   browser = p.chromium.launch_persistent_context(
       user_data_dir="./chrome-profile",
       channel="chrome",
       headless=False,
       no_viewport=True,
   )
   ```
3. Implementar **comportamento humano**:
   - Cliques com curva de Bézier (mouse_path)
   - Digitação com timing variável (60-220ms entre teclas)
   - Scroll suave com pausas
   - Delays aleatórios entre ações (não fixos)
   - Movimentação de mouse para elementos aleatórios da página
4. Configurar fingerprint realista: viewport, user-agent, WebGL, plugins

**Referência**: Usar `patchright` (3.2k stars no GitHub) que já passa Cloudflare, DataDome e Akamai.

**Tempo estimado**: 8-12 horas

### Fase 5: Criar Form Filler Inteligente

**O que**: Sistema que lê qualquer formulário de candidatura e preenche corretamente.

**Arquivos**:
- `src/applypilot/apply/form_detector.py` — novo
- `src/applypilot/apply/field_matcher.py` — novo
- `src/applypilot/apply/question_answering.py` — novo

**Mudanças**:
1. **Field Matcher**: Mapear labels de formulário para campos do perfil usando fuzzy matching:
   - "First Name" → profile.personal.first_name
   - "Phone number" → profile.personal.phone
   - "LinkedIn profile" → profile.personal.linkedin_url
   - "Years of experience" → profile.experience.years_of_experience_total
   - etc. (100+ padrões de labels comuns)
2. **Question Answering**: Para perguntas discursivas, usar LLM com o perfil completo como contexto:
   - "Why do you want to work here?" → LLM gera resposta baseada nas preferências do candidato + descrição da vaga
   - "Describe your experience with X" → LLM busca no perfil e resume
3. **Form Detector**: Identificar o tipo de ATS (LinkedIn Easy Apply, Greenhouse, Lever, Workday, Gupy, etc.) e aplicar estratégia específica
4. **Upload Handler**: Anexar currículo e cover letter nos campos de file upload

**Inspiração**: `linkedin-auto-apply` (jtur671) tem um form-filler com 50+ aliases de campos. `ai-job-agent` (AkbarDevop) tem auto-answer engine para screening questions.

**Tempo estimado**: 15-20 horas

### Fase 6: Autenticação Robusta

**O que**: Login persistente sem precisar copiar perfil.

**Arquivos**:
- `src/applypilot/apply/chrome.py` — novo setup

**Mudanças**:
1. **Cookie Import**: Ao invés de copiar o perfil inteiro, usar um perfil persistente dedicado e importar cookies do Chrome do usuário:
   ```python
   # Abrir Chrome do usuário para extrair cookies
   # Salvar cookies em arquivo
   # Reusar no perfil persistente do worker
   ```
2. **Perfil Persistente**: Manter um único diretório de perfil reutilizado entre execuções (não deletar após cada run)
3. **Primeira vez assistida**: Na primeira execução, abrir Chrome para o usuário fazer login manual (como faz o AIJobHunter), depois reusar a sessão
4. **Detecção de sessão expirada**: Verificar se o login ainda está ativo antes de cada aplicação

**Tempo estimado**: 4-6 horas

### Fase 7: Pipeline Completo + Dashboard

**O que**: Integrar tudo e melhorar a experiência.

**Arquivos**:
- `src/applypilot/apply/launcher.py` — novo worker loop
- `src/applypilot/cli.py` — novos comandos
- `src/applypilot/web/dashboard.html` — melhorias no dashboard

**Mudanças**:
1. Novo worker loop: processa uma vaga por vez com:
   - Verificação de sessão ativa
   - Abrir URL da vaga
   - Detectar tipo de formulário
   - Preencher campos (form filler)
   - Responder perguntas (LLM)
   - Anexar documentos
   - Revisar antes de enviar (modo review)
   - Enviar
2. Modos de operação:
   - `full_auto`: aplica sem intervenção
   - `review`: pausa antes de cada envio para aprovação
   - `watch`: apenas observa e sugere, não envia
3. Dashboard ao vivo com status de cada aplicação

**Tempo estimado**: 10-15 horas

---

## Resumo de Esforço

| Fase | Descrição | Horas | Depende de |
|------|-----------|-------|------------|
| 1 | Expandir perfil do usuário | 2-3 | — |
| 2 | Corrigir currículos (PROJETOS/FORMAÇÃO) | 4-6 | Fase 1 |
| 3 | Substituir DeepSeek por automação estruturada | 20-30 | — |
| 4 | Anti-detecção com Patchright | 8-12 | Fase 3 |
| 5 | Form filler inteligente | 15-20 | Fases 3, 4 |
| 6 | Autenticação robusta | 4-6 | Fase 4 |
| 7 | Pipeline completo + dashboard | 10-15 | Fases 2-6 |
| **Total** | | **63-92 horas** | |

## Arquitetura Proposta (pós-refatoração)

```
┌─────────────────────────────────────────────────────────────┐
│                    applypilot (CLI)                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Discover │  │  Score   │  │  Tailor  │  │ Auto-Apply │ │
│  │ (jobspy) │  │(DeepSeek)│  │(DeepSeek)│  │ (Patchright)│ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Auto-Apply Engine (Patchright)          │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │   │
│  │  │  Cookie  │  │   Form   │  │  Question        │  │   │
│  │  │  Import  │  │  Filler  │  │  Answering (LLM) │  │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │   │
│  │                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │   │
│  │  │   ATS    │  │  Field   │  │  Human Behavior  │  │   │
│  │  │ Detector │  │  Matcher │  │  Simulator       │  │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           Perfil do Usuário (profile.json)           │   │
│  │  • Dados pessoais  • Experiência completa           │   │
│  │  • Projetos        • Realizações                     │   │
│  │  • Certificações   • Educação completa              │   │
│  │  • Respostas padrão para perguntas frequentes       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Próximos Passos Imediatos

1. **Você quer começar pela Fase 1** (expandir o perfil) — isso é rápido e melhora tudo que vem depois
2. **Enquanto isso**, posso pesquisar código dos projetos concorrentes (ai-job-agent, linkedin-auto-apply) para reutilizar lógica
3. **Depois** fazemos a Fase 2 (corrigir currículos) — assim os currículos que você já está aplicando manualmente ficam completos
4. **Por último** as fases 3-7 (automação de verdade)

O que acha?
