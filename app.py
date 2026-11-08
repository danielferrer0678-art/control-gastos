import os
import hmac
import hashlib
import requests
import pandas as pd
import streamlit as st
from datetime import date

st.set_page_config(page_title="Control de gastos", page_icon="💰")

URL = st.secrets["TURSO_URL"].replace("libsql://", "https://")
TOKEN = st.secrets["TURSO_TOKEN"]


# ---------- Conexión a Turso ----------
def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def sql(query, args=None):
    stmt = {"sql": query}
    if args:
        stmt["args"] = [_arg(a) for a in args]
    r = requests.post(
        f"{URL}/v2/pipeline",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]},
        timeout=20,
    )
    r.raise_for_status()
    res = r.json()["results"][0]
    if res["type"] == "error":
        raise Exception(res["error"]["message"])
    result = res["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    rows = [[c.get("value") for c in row] for row in result["rows"]]
    return pd.DataFrame(rows, columns=cols)


# ---------- Tablas ----------
sql("""
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE,
    clave TEXT NOT NULL
)
""")
sql("""
CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    categoria TEXT NOT NULL,
    descripcion TEXT,
    monto REAL NOT NULL
)
""")
sql("""
CREATE TABLE IF NOT EXISTS ingresos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    categoria TEXT NOT NULL,
    descripcion TEXT,
    monto REAL NOT NULL,
    usuario_id INTEGER NOT NULL
)
""")
try:  # agrega la columna del dueño del gasto (solo la primera vez)
    sql("ALTER TABLE gastos ADD COLUMN usuario_id INTEGER")
except Exception:
    pass


# ---------- Contraseñas ----------
def hashear(clave):
    sal = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, 200_000)
    return sal.hex() + "$" + h.hex()


def verificar(clave, guardada):
    sal_hex, h_hex = guardada.split("$")
    h = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(sal_hex), 200_000)
    return hmac.compare_digest(h.hex(), h_hex)


# ---------- Login / Registro ----------
if "usuario_id" not in st.session_state:
    st.title("💰 Control de gastos")
    tab_in, tab_reg = st.tabs(["Iniciar sesión", "Crear cuenta"])

    with tab_in:
        with st.form("login"):
            u = st.text_input("Usuario").strip().lower()
            p = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Entrar")
        if entrar:
            fila = sql("SELECT id, clave FROM usuarios WHERE usuario = ?", [u])
            if not fila.empty and verificar(p, fila.loc[0, "clave"]):
                st.session_state["usuario_id"] = int(fila.loc[0, "id"])
                st.session_state["usuario"] = u
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")

    with tab_reg:
        with st.form("registro"):
            nu = st.text_input("Elige un usuario").strip().lower()
            np1 = st.text_input("Elige una contraseña (mínimo 6 caracteres)", type="password")
            np2 = st.text_input("Repite la contraseña", type="password")
            crear = st.form_submit_button("Crear cuenta")
        if crear:
            if len(nu) < 3:
                st.warning("El usuario debe tener al menos 3 caracteres.")
            elif len(np1) < 6:
                st.warning("La contraseña debe tener al menos 6 caracteres.")
            elif np1 != np2:
                st.warning("Las contraseñas no coinciden.")
            elif not sql("SELECT id FROM usuarios WHERE usuario = ?", [nu]).empty:
                st.error("Ese usuario ya existe, elige otro.")
            else:
                sql("INSERT INTO usuarios (usuario, clave) VALUES (?, ?)", [nu, hashear(np1)])
                st.success("Cuenta creada. Ahora inicia sesión en la otra pestaña.")
    st.stop()


# ---------- App (solo con sesión iniciada) ----------
UID = st.session_state["usuario_id"]

st.sidebar.write(f"👤 {st.session_state['usuario']}")
if st.sidebar.button("Cerrar sesión"):
    st.session_state.clear()
    st.rerun()

st.title("💰 Control de gastos")


# ---------- Apartado de ingresos ----------
st.header("💵 Mis ingresos")

categorias_ingresos = [
    "Sueldo",
    "Beca",
    "Negocio",
    "Regalo",
    "Otros"
]

with st.form("nuevo_ingreso", clear_on_submit=True):
    c1, c2 = st.columns(2)

    categoria_ingreso = c1.selectbox(
        "Tipo de ingreso",
        categorias_ingresos
    )

    monto_ingreso = c2.number_input(
        "Cantidad recibida ($)",
        min_value=0.0,
        step=50.0
    )

    descripcion_ingreso = st.text_input(
        "Descripción del ingreso"
    )

    fecha_ingreso = st.date_input(
        "Fecha del ingreso",
        value=date.today()
    )

    guardar_ingreso = st.form_submit_button(
        "Guardar ingreso"
    )

if guardar_ingreso:
    if monto_ingreso <= 0:
        st.warning("El monto debe ser mayor a cero.")
    else:
        sql(
            "INSERT INTO ingresos "
            "(fecha, categoria, descripcion, monto, usuario_id) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                fecha_ingreso.isoformat(),
                categoria_ingreso,
                descripcion_ingreso,
                float(monto_ingreso),
                UID
            ]
        )
        st.success("¡Ingreso registrado correctamente!")
        st.rerun()

# Consultar ingresos del usuario
df_ingresos = sql(
    "SELECT fecha, categoria, descripcion, monto "
    "FROM ingresos WHERE usuario_id = ? "
    "ORDER BY fecha DESC, id DESC",
    [UID]
)

total_ingresos = (
    df_ingresos["monto"].astype(float).sum()
    if not df_ingresos.empty else 0
)

st.metric("Total de ingresos", f"${total_ingresos:,.2f}")

st.subheader("Historial de ingresos")

if df_ingresos.empty:
    st.info("Todavía no tienes ingresos registrados.")
else:
    st.dataframe(
        df_ingresos,
        hide_index=True,
        use_container_width=True
    )


st.subheader("Registrar un gasto")
categorias = ["Comida", "Transporte", "Entretenimiento", "Ropa",
              "Salud", "Servicios", "Escuela", "Otros"]

with st.form("nuevo_gasto", clear_on_submit=True):
    c1, c2 = st.columns(2)
    categoria = c1.selectbox("Categoría", categorias)
    monto = c2.number_input("Monto ($)", min_value=0.0, step=10.0)
    descripcion = st.text_input("Descripción")
    fecha = st.date_input("Fecha", value=date.today())
    guardar = st.form_submit_button("Guardar gasto")

if guardar:
    if monto <= 0:
        st.warning("El monto debe ser mayor a 0.")
    else:
        sql("INSERT INTO gastos (fecha, categoria, descripcion, monto, usuario_id) VALUES (?, ?, ?, ?, ?)",
            [fecha.isoformat(), categoria, descripcion, float(monto), UID])
        st.success(f"Guardado: {categoria} - ${monto:,.2f}")

df = sql("SELECT id, fecha, categoria, descripcion, monto FROM gastos "
         "WHERE usuario_id = ? ORDER BY fecha DESC, id DESC", [UID])

if df.empty:
    st.info("Aún no tienes gastos registrados.")
    st.stop()

df["monto"] = df["monto"].astype(float)
df["id"] = df["id"].astype(int)
df["categoria"] = df["categoria"].str.strip().str.capitalize()

st.metric("Total gastado", f"${df['monto'].sum():,.2f}")

st.subheader("¿En qué se va tu dinero?")
resumen = (df.groupby("categoria")["monto"].sum()
             .sort_values(ascending=False).reset_index())

col1, col2 = st.columns(2)
with col1:
    st.bar_chart(resumen.set_index("categoria"))
with col2:
    st.dataframe(resumen.rename(columns={"monto": "total"}),
                 hide_index=True, use_container_width=True)

st.subheader("Historial")
st.dataframe(df, hide_index=True, use_container_width=True)

with st.expander("Borrar un gasto"):
    id_borrar = st.number_input("ID del gasto", min_value=1, step=1)
    if st.button("Borrar"):
        sql("DELETE FROM gastos WHERE id = ? AND usuario_id = ?", [int(id_borrar), UID])
        st.success("Gasto borrado. Recarga la página para ver el cambio.")
