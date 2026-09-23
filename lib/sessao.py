"""Identificação do utilizador e permissões.

O email vem da autenticação do Streamlit Community Cloud (app privada com
convites por email) e é associado a um registo da folha «membros».

Perfis:
    colaborador  regista e submete as próprias horas
    gestor       aprova as horas da sua equipa; vê custos e orçamentos
    admin        acesso total (taxas, perfis, fecho de períodos)

Administradores de arranque: emails listados em secrets [app] admins são
sempre admin, mesmo antes de existirem membros. Se não houver nenhum admin
definido (nem nos secrets nem na folha), o utilizador autenticado é tratado
como admin para poder fazer a configuração inicial — com aviso visível.

Modo local: ao correr em `streamlit run` sem autenticação, o email é «local».
Só com secrets [app] modo_local = true é possível escolher na barra lateral
o membro a simular. Nunca ativar isto na app publicada.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from lib import data
from lib.config import HORAS_SEMANA_OMISSAO, PERFIS


@dataclass
class Utilizador:
    id: str
    nome: str
    email: str
    perfil: str
    equipa_id: str
    horas_semana: float
    arranque: bool = False  # admin provisório (sem admins definidos)

    @property
    def admin(self) -> bool:
        return self.perfil == "admin"

    @property
    def gestor(self) -> bool:
        return self.perfil in {"gestor", "admin"}

    @property
    def ve_financeiro(self) -> bool:
        """Custos, taxas e valores faturáveis."""
        return self.gestor


def _app_secrets() -> dict:
    try:
        return dict(st.secrets.get("app", {}))
    except Exception:  # noqa: BLE001  (sem ficheiro de secrets)
        return {}


def _admins_secrets() -> set[str]:
    return {str(e).strip().lower() for e in _app_secrets().get("admins", []) if str(e).strip()}


def modo_local() -> bool:
    return bool(_app_secrets().get("modo_local", False)) and data.utilizador_atual() == "local"


def _perfil(valor: str) -> str:
    v = str(valor or "").strip().lower()
    return v if v in PERFIS else "colaborador"


def _de_linha(m: pd.Series, email: str) -> Utilizador:
    return Utilizador(
        id=m["id"],
        nome=m["nome"],
        email=email or m.get("email", ""),
        perfil=_perfil(m.get("perfil")),
        equipa_id=m.get("equipa_id", ""),
        horas_semana=float(m.get("horas_semana") or 0) or HORAS_SEMANA_OMISSAO,
    )


def utilizador(membros: pd.DataFrame | None = None) -> Utilizador | None:
    """Utilizador atual associado a um membro ativo, ou None."""
    membros = data.ler("membros") if membros is None else membros
    ativos = membros[membros["ativo"].astype(str).str.strip().str.lower() != "não"] \
        if not membros.empty else membros

    if modo_local():
        if ativos.empty:
            return None
        opcoes = dict(zip(ativos["id"], ativos["nome"]))
        escolhido = st.sidebar.selectbox(
            "🧪 Simular membro (modo local)", list(opcoes.keys()),
            format_func=lambda i: opcoes[i], key="_simular_membro",
        )
        u = _de_linha(ativos[ativos["id"] == escolhido].iloc[0], "")
    else:
        email = data.utilizador_atual().strip().lower()
        if email == "local" or ativos.empty:
            return None
        correspondencia = ativos[ativos["email"].astype(str).str.strip().str.lower() == email]
        if correspondencia.empty:
            return None
        u = _de_linha(correspondencia.iloc[0], email)

    if u.email.lower() in _admins_secrets():
        u.perfil = "admin"

    if not existe_admin(membros):
        u.perfil = "admin"
        u.arranque = True
    return u


def existe_admin(membros: pd.DataFrame) -> bool:
    """Há pelo menos um admin definido (secrets ou perfil na folha)?"""
    if _admins_secrets():
        return True
    return not membros.empty and bool((membros["perfil"].astype(str).str.lower() == "admin").any())


def exigir_utilizador(membros: pd.DataFrame | None = None) -> Utilizador:
    """Para a página com uma mensagem clara se o utilizador não estiver associado."""
    u = utilizador(membros)
    if u is None:
        email = data.utilizador_atual()
        if email == "local" and not modo_local():
            st.error(
                "Sem utilizador autenticado. Em local, ativa `modo_local = true` "
                "na secção `[app]` do `secrets.toml` para simular um membro.",
                icon="🔒",
            )
        else:
            st.error(
                f"O email **{email}** não está associado a nenhum membro ativo. "
                "Pede a um administrador para o acrescentar em **Equipas → Membros**.",
                icon="🔒",
            )
        st.stop()
    return u


def cartao_lateral(u: Utilizador) -> None:
    with st.sidebar:
        st.markdown(f"**{u.nome}**  \n{u.perfil.capitalize()}")
        if u.arranque:
            st.warning(
                "Não há administradores definidos: estás com acesso de admin "
                "provisório. Atribui o perfil «admin» a alguém em Equipas → Membros.",
                icon="⚠️",
            )


# ==========================================================================
# Permissões sobre outros membros
# ==========================================================================
def membros_visiveis(u: Utilizador, membros: pd.DataFrame) -> pd.DataFrame:
    """Membros cujas horas o utilizador pode ver."""
    if membros.empty:
        return membros
    if u.admin:
        return membros
    if u.perfil == "gestor":
        return membros[(membros["equipa_id"] == u.equipa_id) | (membros["id"] == u.id)]
    return membros[membros["id"] == u.id]


def pode_aprovar(u: Utilizador, membro: pd.Series) -> bool:
    """Admin aprova todos (incluindo a si próprio, numa equipa pequena pode ser o único).
    Gestor aprova a própria equipa, exceto a si próprio."""
    if u.admin:
        return True
    if u.perfil == "gestor":
        return membro["equipa_id"] == u.equipa_id and membro["id"] != u.id
    return False
