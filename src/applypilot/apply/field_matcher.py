"""Maps form field labels to profile fields using fuzzy matching."""

import re
from typing import Any

FIELD_PATTERNS: list[tuple[re.Pattern, str, str | None]] = [
    # ── Name fields ──────────────────────────────────────────────────
    (re.compile(r"^(?:full\s+)?name$", re.I), "personal.full_name", "full"),
    (re.compile(r"^(?:seu\s+)?nome$", re.I), "personal.full_name", "full"),
    (re.compile(r"^(?:your\s+)?name$", re.I), "personal.full_name", "full"),
    (re.compile(r"nome\s*completo", re.I), "personal.full_name", "full"),
    (re.compile(r"^(?:first|primeir|given|fore).*name", re.I), "personal.full_name", "first"),
    (re.compile(r"primeiro\s*nome", re.I), "personal.full_name", "first"),
    (re.compile(r"^(?:last|sobren|sóbren|family|surname|second).*name", re.I), "personal.full_name", "last"),
    (re.compile(r"sobrenome|último\s*nome|ultimo\s*nome", re.I), "personal.full_name", "last"),
    (re.compile(r"preferred.*name", re.I), "personal.preferred_name", None),
    (re.compile(r"como\s*gostaria\s*de\s*ser\s*chamado", re.I), "personal.preferred_name", None),
    (re.compile(r"apelido|nickname", re.I), "personal.preferred_name", None),
    (re.compile(r"middle.*name|nome\s*do\s*meio", re.I), None, None),

    # ── Contact fields ───────────────────────────────────────────────
    (re.compile(r"e[-\s]?mail|email|e-mail", re.I), "personal.email", None),
    (re.compile(r"correio\s*eletr[oô]nico", re.I), "personal.email", None),
    (re.compile(r"phone|telefone|celular|mobile|cell|contact.*number|phone.*number", re.I), "personal.phone", None),
    (re.compile(r"whatsapp|whats\s*app|zap", re.I), "personal.phone", None),
    (re.compile(r"telefone\s*(celular|fixo|residencial|comercial)", re.I), "personal.phone", None),
    (re.compile(r"contato|telefone\s*para\s*contato", re.I), "personal.phone", None),
    (re.compile(r"dd|ddd", re.I), None, None),

    # ── LinkedIn ─────────────────────────────────────────────────────
    (re.compile(r"linked[-\s]?in|linkedin", re.I), "personal.linkedin_url", None),
    (re.compile(r"perfil\s*do\s*linkedin", re.I), "personal.linkedin_url", None),

    # ── Social Media ─────────────────────────────────────────────────
    (re.compile(r"instagram", re.I), "personal.portfolio_url", None),
    (re.compile(r"facebook", re.I), "personal.portfolio_url", None),
    (re.compile(r"twitter|x\.com", re.I), "personal.portfolio_url", None),
    (re.compile(r"youtube", re.I), "personal.portfolio_url", None),
    (re.compile(r"tiktok", re.I), "personal.portfolio_url", None),

    # ── Location / Address ───────────────────────────────────────────
    (re.compile(r"city|cidade", re.I), "personal.city", None),
    (re.compile(r"state|province|estado", re.I), "personal.province_state", None),
    (re.compile(r"country|pa[íi]s|pais", re.I), "personal.country", None),
    (re.compile(r"address|endere[çc]o|endereco|logradouro", re.I), "personal.address", None),
    (re.compile(r"postal|zip|cep|c[oó]digo\s*postal", re.I), "personal.postal_code", None),
    (re.compile(r"bairro|neighborhood|distrito", re.I), "personal.address", None),
    (re.compile(r"n[uú]mero.*(?:casa|resid[eê]ncia)", re.I), None, None),
    (re.compile(r"complemento", re.I), None, None),
    (re.compile(r"localiza[çc][ãa]o|location", re.I), "personal.city", None),
    (re.compile(r"regi[ãa]o|region", re.I), "personal.province_state", None),

    # ── Brazilian Documents ──────────────────────────────────────────
    (re.compile(r"cpf|cnpj", re.I), None, None),
    (re.compile(r"rg|identidade|identidade\s*civil", re.I), None, None),
    (re.compile(r"pis|nit|pasep|nis", re.I), None, None),
    (re.compile(r"t[íi]tulo\s*de\s*eleitor", re.I), None, None),
    (re.compile(r"carteira\s*de\s*trabalho|ctps", re.I), None, None),
    (re.compile(r"passaporte|passport", re.I), None, None),
    (re.compile(r"nacionalidade|nationality", re.I), "work_authorization.work_permit_type", None),
    (re.compile(r"naturalidade|born", re.I), None, None),
    (re.compile(r"data\s*de\s*nascimento|birth.*date|date.*birth|nascimento", re.I), None, None),
    (re.compile(r"idade|age", re.I), None, None),
    (re.compile(r"estado\s*civil|civil\s*status", re.I), None, None),
    (re.compile(r"g[êe]nero|sexo|gender", re.I), "eeo_voluntary.gender", None),

    # ── Work Authorization ───────────────────────────────────────────
    (re.compile(r"(?:work\s*)?authorized?|legally.*work|work.*permit|autorizad[oa].*trabalho", re.I), "work_authorization.legally_authorized_to_work", None),
    (re.compile(r"sponsorship|sponsor|visa|visto|precisa.*visto|necessita.*visto", re.I), "work_authorization.require_sponsorship", None),
    (re.compile(r"(?:work\s*)?permit.*type|tipo.*permiss[ãa]o|tipo.*autoriza[çc][ãa]o", re.I), "work_authorization.work_permit_type", None),
    (re.compile(r"direito\s*de\s*trabalhar|right.*work|elegibilidade|eligible.*work", re.I), "work_authorization.legally_authorized_to_work", None),
    (re.compile(r"cidadania|citizen|citizenship|cidad[ãa]o|brasileiro|nascido.*brasil", re.I), "work_authorization.work_permit_type", None),

    # ── Compensation ─────────────────────────────────────────────────
    (re.compile(r"salary|sal[áa]rio|salario|pretens[ãa]o|pretensao|expected.*pay|desired.*pay|pretens[ãa]o\s*salarial", re.I), "compensation.salary_expectation", None),
    (re.compile(r"salary.*range|faixa\s*salaria", re.I), "compensation.salary_range_min", None),
    (re.compile(r"expectativa\s*salarial|expectativa\s*financeira|quanto\s*voc[êe].*ganhar", re.I), "compensation.salary_expectation", None),
    (re.compile(r"moeda|currency|brl|real", re.I), "compensation.salary_currency", None),
    (re.compile(r"benef[íi]cios|benefits|vale.*refei[çc][ãa]o|vale.*alimenta[çc][ãa]o|\bvt\b|\bva\b|\bvr\b", re.I), None, None),

    # ── Experience & Education ───────────────────────────────────────
    (re.compile(r"years.*(?:exp|experience|experi[êe]ncia|experiencia)|anos.*(?:experi[êe]ncia|experiencia|exp)", re.I), "experience.years_of_experience_total", None),
    (re.compile(r"education.*level|n[íi]vel.*escolar|nivel.*escolar|highest.*degree|education", re.I), "experience.education_level", None),
    (re.compile(r"current.*(?:company|employer|empresa)", re.I), "experience.current_company", None),
    (re.compile(r"current.*(?:title|job|role|cargo|position|fun[çc][ãa]o)", re.I), "experience.current_job_title", None),
    (re.compile(r"empresa\s*atual|empregador\s*atual|employer|trabalha\s*atualmente", re.I), "experience.current_company", None),
    (re.compile(r"cargo\s*atual|posi[çc][ãa]o\s*atual|current\s*position|current\s*job", re.I), "experience.current_job_title", None),
    (re.compile(r"experi[êe]ncia\s*anterior|trabalho\s*anterior|previous.*(?:job|employer|company)", re.I), "experience.current_company", None),

    # ── Education Specific ────────────────────────────────────────────
    (re.compile(r"institui[çc][ãa]o\s*de\s*ensino|institution|school|faculdade|universidade|university", re.I), "educacao_completa", None),
    (re.compile(r"curso|course|degree|gradua[çc][ãa]o|p[oós]\s*gradua[çc][ãa]o|mestrado|doutorado|especializa[çc][ãa]o", re.I), "educacao_completa", None),
    (re.compile(r"ano\s*de\s*conclus[ãa]o|graduation.*year|formatura|conclu[íi]do|ano.*formatura", re.I), "educacao_completa", None),
    (re.compile(r"n[íi]vel\s*de\s*instru[çc][ãa]o|escolaridade|forma[çc][ãa]o.*acad[êe]mica|grau\s*de\s*instru[çc][ãa]o", re.I), "experience.education_level", None),

    # ── Skills ────────────────────────────────────────────────────────
    (re.compile(r"skills|habilidades|compet[êe]ncias|conhecimentos?|aptid[ãa]o|aptid[oõ]es", re.I), "skills_boundary.marketing_strategy", None),
    (re.compile(r"principais\s*habilidades|habilidades\s*t[eé]cnicas|technical.*skills|top.*skills", re.I), "skills_boundary.marketing_strategy", None),
    (re.compile(r"linguagens|programa[çc][ãa]o|languages", re.I), "skills_boundary.languages", None),
    (re.compile(r"idiomas|languages", re.I), "skills_boundary.languages", None),
    (re.compile(r"n[íi]vel\s*de\s*ingl[êe]s|english.*level|ingl[êe]s|english\s*fluency", re.I), "respostas_padrao.english_level", None),

    # ── Availability ──────────────────────────────────────────────────
    (re.compile(r"start.*date|available.*date|earliest.*start|data.*in[íi]cio|dispon[íi]vel.*data|quando\s*pode\s*come[çc]ar", re.I), "availability.earliest_start_date", None),
    (re.compile(r"disponibilidade|availability|available|dispon[íi]vel\s*para\s*in[íi]cio", re.I), "availability.earliest_start_date", None),
    (re.compile(r"full.?time|tempo.*integral|per[íi]odo\s*integral|integral", re.I), "availability.available_for_full_time", None),
    (re.compile(r"contract|contrato|freelance|aut[ôo]nomo|pj", re.I), "availability.available_for_contract", None),
    (re.compile(r"meio\s*per[íi]odo|part.?time|meio\s*expediente", re.I), None, None),
    (re.compile(r"est[áa]gio|internship|trainee|jovem\s*aprendiz", re.I), None, None),
    (re.compile(r"home.?office|remoto|remoto|teletrabalho|trabalho\s*remoto|remote|work\s*from\s*home|wfh", re.I), "respostas_padrao.remote_work_preference", None),
    (re.compile(r"presencial|h[ií]brido|hibrido|on.?site", re.I), "respostas_padrao.remote_work_preference", None),
    (re.compile(r"turno|shift|hor[áa]rio|horas\s*dispon[íi]veis|available.*hours", re.I), None, None),

    # ── Relocation & Travel ───────────────────────────────────────────
    (re.compile(r"relocate|realocar|mudan[çc]a|mudanca|disposto.*mudar|mudar.*cidade|mudar.*pa[íi]s", re.I), "respostas_padrao.willing_to_relocate", None),
    (re.compile(r"travel|viagem|viagens|dispon[íi]vel.*viagem|disponibilidade.*viagem", re.I), "respostas_padrao.willing_to_travel", None),
    (re.compile(r"mobilidade|mobility|transporte|transport", re.I), "respostas_padrao.willing_to_relocate", None),
    (re.compile(r"carteira\s*de\s*motorista|driver.*license|cnh|habilita[çc][ãa]o", re.I), None, None),

    # ── Job Target ────────────────────────────────────────────────────
    (re.compile(r"cargo\s*de\s*interesse|cargo\s*desejado|position.*interest|job.*interest|role.*interest", re.I), "experience.target_role", None),
    (re.compile(r"[áa]rea\s*de\s*interesse|area.*interest|interesse.*profissional", re.I), "experience.current_job_title", None),
    (re.compile(r"como\s*voc[êe].*ouviu|how.*hear|how.*find|how.*know|how.*discover|how.*learn|onde\s*(?:conheceu|encontrou|viu|ouviu)|onde\s*voc[êe].*encontrou|encontrou.*vaga", re.I), "respostas_padrao.how_did_you_hear_about_this_position", None),
    (re.compile(r"por\s*que\s*voc[êe].*trabalhar|why.*work|why.*want|why.*interested|why.*apply|motivo.*interesse|motiva[çc][ãa]o", re.I), "respostas_padrao.why_leave_current", None),
    (re.compile(r"conte\s*sobre|fale\s*sobre|tell.*about|tell.*yourself|descreva|describe|sobre\s*voc[êe]", re.I), "respostas_padrao.why_qualified", None),
    (re.compile(r"qual\s*[oã].*maior\s*(?:fraqueza|defeito|ponto\s*fraco)", re.I), "respostas_padrao.why_qualified", None),
    (re.compile(r"qual\s*[oã].*maior\s*(?:qualidade|ponto\s*forte|forte)", re.I), "respostas_padrao.why_qualified", None),
    (re.compile(r"onde\s*voc[êe]\s*.*5.*anos|5.*year.*plan|future.*plan|objetivos.*futuro|objetivos.*carreira|career.*goal|crescimento", re.I), "respostas_padrao.why_leave_current", None),
    (re.compile(r"sal[áa]rio|pretens[ãa]o\s*salarial|expectativa\s*salarial|quanto\s*espera|faixa\s*salarial", re.I), "compensation.salary_expectation", None),

    # ── Portfolio / Website ───────────────────────────────────────────
    (re.compile(r"portfolio|portf[oó]lio|portifolio", re.I), "personal.portfolio_url", None),
    (re.compile(r"website|site|web\s*site|p[áa]gina.*web|site\s*pessoal", re.I), "personal.website_url", None),
    (re.compile(r"github", re.I), "personal.github_url", None),
    (re.compile(r"behance|dribbble|artstation", re.I), "personal.portfolio_url", None),

    # ── EEO / Diversity ───────────────────────────────────────────────
    (re.compile(r"race|ra[çc]a|ethnic|etnia|cor", re.I), "eeo_voluntary.race_ethnicity", None),
    (re.compile(r"veteran|veterano", re.I), "eeo_voluntary.veteran_status", None),
    (re.compile(r"disabilit?y|defici[êe]ncia|deficiencia|pcd|pessoa\s*com\s*defici[êe]ncia|necessidades\s*especiais", re.I), "eeo_voluntary.disability_status", None),
    (re.compile(r"lgbt|sexual.*orientation|orienta[çc][ãa]o\s*sexual", re.I), None, None),

    # ── File uploads ──────────────────────────────────────────────────
    (re.compile(r"resume|curr[íi]culo|curriculo|cv|curr[íi]culo\s*lattes", re.I), "__resume__", None),
    (re.compile(r"cover.*letter|carta.*apresenta[çc][ãa]o|coverletter", re.I), "__cover_letter__", None),
    (re.compile(r"anexar|upload|attach|adicionar\s*arquivo|selecionar\s*arquivo|choose\s*file|browse", re.I), "__resume__", None),

    # ── Gupy-specific ──────────────────────────────────────────────────
    (re.compile(r"acessar\s*conta|entrar|sign\s*in|signin|login|log\s*in", re.I), None, None),
    (re.compile(r"criar\s*conta|create.*account|register|cadastre-se|cadastro|cadastrar", re.I), None, None),
    (re.compile(r"senha|password|passwd", re.I), None, None),
    (re.compile(r"email.*ou.*cpf|cpf.*ou.*email", re.I), "personal.email", None),
]

# Known boolean labels (yes/no questions)
YES_NO_LABELS: list[tuple[re.Pattern, str]] = [
    # Age / eligibility
    (re.compile(r"over\s*18|maior.*18|18\s*anos|acima\s*de\s*18|tem\s*mais\s*de\s*18", re.I), "yes"),
    (re.compile(r"menor.*18|under\s*18", re.I), "no"),

    # Work authorization
    (re.compile(r"legally.*authorized?|authorized?.*work.*(?:us|br|canada|uk|brasil)", re.I), "yes"),
    (re.compile(r"direito.*trabalho|autorizad.*trabalh|eleg[íi]vel.*trabalh", re.I), "yes"),

    # Sponsorship / visa
    (re.compile(r"sponsorship|require.*visa|need.*visa|precisa.*visto|necessita.*visto|patroc[íi]nio", re.I), "no"),
    (re.compile(r"precisa.*autoriza[çc][ãa]o|need.*permit|visa.*required", re.I), "no"),

    # Criminal
    (re.compile(r"felony|criminal|crime|condenado|antecedente|processo.*criminal|ficha.*limpa|j[áa].*condenad", re.I), "no"),

    # Education
    (re.compile(r"college.*graduate|university.*graduate|superior.*completo|forma[çc][ãa]o.*superior|ensino.*superior.*completo|graduad", re.I), "yes"),
    (re.compile(r"high.*school.*(?:graduate|diploma)|ensino.*m[eé]dio.*completo|segundo.*grau.*completo", re.I), "yes"),

    # Language
    (re.compile(r"fluent.*english|ingl[êe]s.*fluente|fluente.*ingl[êe]s|nativo.*ingl[êe]s", re.I), "yes"),
    (re.compile(r"fluent.*portuguese|portugu[êe]s.*fluente|nativo.*portugu[êe]s|l[í]ngua.*materna.*portugu[êe]s", re.I), "yes"),

    # Availability
    (re.compile(r"available\s*to\s*start|immediately|imediatamente|imediato|start.*immediately|dispon[íi]vel\s*imediato", re.I), "yes"),
    (re.compile(r"willing.*(?:full.?time|tempo.*integral|integral)", re.I), "yes"),
    (re.compile(r"open\s*to\s*relocate|willing.*relocate|dispon[íi]vel.*mudar|disposto.*mudar", re.I), "yes"),
    (re.compile(r"available.*travel|willing.*travel|dispon[íi]vel.*viagem|disponibilidade.*viagem", re.I), "yes"),

    # EEO
    (re.compile(r"decline.*self.?identify|prefiro\s*n[ãa]o|prefiro\s*não|choose.*not|not.*wish.*answer|i\s*do\s*not\s*wish", re.I), "I do not wish to answer"),
    (re.compile(r"female|feminino|mulher", re.I), "Female"),
    (re.compile(r"male|masculino|homem", re.I), "Male"),
    (re.compile(r"protected.*veteran|veteran.*status", re.I), "I am not a protected veteran"),
    (re.compile(r"disabilit?y.*status", re.I), "I do not wish to answer"),

    # Gupy-specific radio questions
    (re.compile(r"indicou.*voc[êe]|algu[eé]m.*trabalha.*indicou", re.I), "no"),
    (re.compile(r"trabalha\s*na\s*empresa", re.I), "no"),
    (re.compile(r"^(sim|yes)$", re.I), "yes"),
    (re.compile(r"^(n[aã]o|no)$", re.I), "no"),

    # Location / remote work
    (re.compile(r"trabalharia.*presencial|presencialmente|disposto.*presencial", re.I), "yes"),
    (re.compile(r"trabalharia.*remoto|home.?office", re.I), "yes"),
]


def resolve_label(label: str, profile: dict[str, Any]) -> dict | None:
    """Match a form field label to a profile field."""
    label_clean = re.sub(r"[:\*\?\[\]\(\)]", " ", label).strip()

    for pattern, field_path, name_part in FIELD_PATTERNS:
        if not pattern.search(label_clean):
            continue

        if field_path is None:
            # Known field but no data to fill
            return None

        if field_path == "__resume__":
            return {"type": "resume_upload"}
        if field_path == "__cover_letter__":
            return {"type": "cover_letter_upload"}

        value = _get_nested(profile, field_path)
        if value is None and name_part:
            full_name = _get_nested(profile, "personal.full_name") or ""
            parts = full_name.strip().split()
            if name_part == "first" and parts:
                value = parts[0]
            elif name_part == "last" and len(parts) > 1:
                value = parts[-1]

        # Handle list fields (skills_boundary.*, projetos, educacao_completa)
        if isinstance(value, list):
            if field_path.startswith("skills_boundary"):
                value = ", ".join(value)
            elif field_path == "educacao_completa":
                entries = []
                for e in value[:3]:
                    if isinstance(e, dict):
                        entries.append(f"{e.get('curso', '')} - {e.get('instituicao', '')} ({e.get('ano', '')})")
                value = "; ".join(entries)
            elif field_path.startswith("projetos"):
                entries = []
                for p in value[:2]:
                    if isinstance(p, dict):
                        entries.append(p.get("nome", ""))
                value = "; ".join(entries)

        if value:
            return {"type": "text", "value": str(value)}

    return None


def resolve_yes_no(label: str) -> str | None:
    """Check if a label matches a known yes/no question."""
    label_clean = re.sub(r"[:\*\?\[\]\(\)]", " ", label).strip()
    for pattern, default in YES_NO_LABELS:
        if pattern.search(label_clean):
            return default
    return None


def _get_nested(obj: dict, path: str) -> Any:
    """Get a nested value from a dict using dot notation."""
    if not path:
        return None
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
