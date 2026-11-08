from datetime import date
import hashlib
import hmac
import os
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Control de gastos y deudas", page_icon="💰", layout="wide"
)

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
    monto REAL NOT NULL,
    usuario_id INTEGER NOT NULL
)
""")
sql("""
CREATE TABLE IF NOT EXISTS deudas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona TEXT NOT NULL,
    tipo TEXT NOT NULL,
    monto_total REAL NOT NULL,
    monto_pagado REAL NOT NULL,
    estado TEXT NOT NULL,
    fecha_limite TEXT NOT NULL,
    usuario_id INTEGER NOT NULL
)
""")
sql("""
CREATE TABLE IF NOT EXISTS metas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    monto_objetivo REAL NOT NULL,
    monto_actual REAL NOT NULL,
    fecha_limite TEXT NOT NULL,
    usuario_id INTEGER NOT NULL
)
""")

# NUEVA TABLA PARA PRESUPUESTO MENSUAL
sql("""
CREATE TABLE IF NOT EXISTS presupuestos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mes_año TEXT NOT NULL,
    monto_limite REAL NOT NULL,
    usuario_id INTEGER NOT NULL,
    UNIQUE(mes_año, usuario_id)
)
""")


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
  st.title("💰 Control de Gastos y Deudas")
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
      np1 = st.text_input(
          "Elige una contraseña (mínimo 6 caracteres)", type="password"
      )
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
        sql(
            "INSERT INTO usuarios (usuario, clave) VALUES (?, ?)",
            [nu, hashear(np1)],
        )
        st.success("Cuenta creada. Ahora inicia sesión en la otra pestaña.")
  st.stop()


# ---------- App (solo con sesión iniciada) ----------
UID = st.session_state["usuario_id"]

with st.sidebar:
  st.write(f"👤 **{st.session_state['usuario']}**")
  if st.button("Cerrar sesión"):
    st.session_state.clear()
    st.rerun()

  st.markdown("---")
  st.subheader("Menú principal")
  menu = st.radio(
      "Selecciona un apartado:",
      [
          "📉 Control de Gastos",
          "💳 Control de Deudas",
          "🎯 Metas de Ahorro",
          "📊 Presupuesto Mensual",
      ],
  )

# ==================== APARTADO: GASTOS ====================
if menu == "📉 Control de Gastos":
  st.header("📉 Control de Gastos")
  categorias = [
      "Comida",
      "Transporte",
      "Entretenimiento",
      "Ropa",
      "Salud",
      "Servicios",
      "Escuela",
      "Otros",
  ]

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
      sql(
          "INSERT INTO gastos (fecha, categoria, descripcion, monto,"
          " usuario_id) VALUES (?, ?, ?, ?, ?)",
          [fecha.isoformat(), categoria, descripcion, float(monto), UID],
      )
      st.success(f"Guardado: {categoria} - ${monto:,.2f}")
      st.rerun()

  df = sql(
      "SELECT id, fecha, categoria, descripcion, monto FROM gastos "
      "WHERE usuario_id = ? ORDER BY fecha DESC, id DESC",
      [UID],
  )

  if not df.empty:
    df["monto"] = df["monto"].astype(float)
    df["id"] = df["id"].astype(int)
    df["categoria"] = df["categoria"].str.strip().str.capitalize()
    df["fecha"] = pd.to_datetime(df["fecha"])

    st.subheader("📅 Resumen de Gasto Mensual")
    df["mes_año"] = df["fecha"].dt.to_period("M").astype(str)
    meses_disponibles = sorted(df["mes_año"].unique(), reverse=True)

    mes_seleccionado = st.selectbox(
        "Selecciona el mes a consultar:", meses_disponibles
    )

    df_filtrado = df[df["mes_año"] == mes_seleccionado]
    total_mes = df_filtrado["monto"].sum()

    st.metric(f"Total gastado en {mes_seleccionado}", f"${total_mes:,.2f}")

    if not df_filtrado.empty:
      st.markdown(f"**Desglose por categoría ({mes_seleccionado}):**")
      resumen_mes = (
          df_filtrado.groupby("categoria")["monto"]
          .sum()
          .sort_values(ascending=False)
          .reset_index()
      )

      col1, col2 = st.columns(2)
      with col1:
        st.bar_chart(resumen_mes.set_index("categoria"))
      with col2:
        st.dataframe(
            resumen_mes.rename(columns={"monto": "total"}),
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Historial de Gastos")
    df_mostrar = df.copy()
    df_mostrar["fecha"] = df_mostrar["fecha"].dt.strftime("%Y-%m-%d")
    st.dataframe(
        df_mostrar.drop(columns=["mes_año"]),
        hide_index=True,
        use_container_width=True,
    )

    with st.expander("✏️ Editar o 🗑️ Borrar un Gasto"):
      id_gasto_sel = st.number_input(
          "Ingresa el ID del gasto a modificar/borrar",
          min_value=1,
          step=1,
          key="input_edit_gasto",
      )

      gasto_encontrado = sql(
          "SELECT fecha, categoria, descripcion, monto FROM gastos WHERE id ="
          " ? AND usuario_id = ?",
          [int(id_gasto_sel), UID],
      )

      if not gasto_encontrado.empty:
        c_act = gasto_encontrado.loc[0, "categoria"]
        d_act = gasto_encontrado.loc[0, "descripcion"]
        m_act = float(gasto_encontrado.loc[0, "monto"])

        with st.form("form_editar_gasto"):
          st.write(f"Editando el gasto con ID: **{id_gasto_sel}**")
          nueva_cat = st.selectbox(
              "Nueva Categoría",
              categorias,
              index=(
                  categorias.index(c_act) if c_act in categorias else 0
              ),
          )
          nuevo_monto = st.number_input(
              "Nuevo Monto ($)", value=m_act, min_value=0.0
          )
          nueva_desc = st.text_input("Nueva Descripción", value=str(d_act))
          actualizar_btn = st.form_submit_button("Guardar cambios 💾")

          if actualizar_btn:
            sql(
                "UPDATE gastos SET categoria = ?, monto = ?, descripcion = ? WHERE"
                " id = ? AND usuario_id = ?",
                [nueva_cat, float(nuevo_monto), nueva_desc, int(id_gasto_sel), UID],
            )
            st.success("¡Gasto actualizado con éxito!")
            st.rerun()

        if st.button("Eliminar este gasto 🗑️", key="btn_del_gasto"):
          sql(
              "DELETE FROM gastos WHERE id = ? AND usuario_id = ?",
              [int(id_gasto_sel), UID],
          )
          st.success("Gasto borrado correctamente.")
          st.rerun()
      else:
        st.info(
            "Ingresa un ID válido de la lista superior para editar o borrar."
        )
  else:
    st.info("Aún no tienes gastos registrados.")

# ==================== APARTADO: DEUDAS ====================
elif menu == "💳 Control de Deudas":
  st.header("💳 Control de Deudas y Préstamos")

  with st.form("nuevo_deuda", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
      persona = st.text_input(
          "Persona o Entidad", placeholder="Ej. Juan Pérez o Banco"
      )
      tipo_deuda = st.selectbox(
          "Tipo", ["Debo (Deuda pendiente) 🔴", "Me deben (Préstamo a favor) 🟢"]
      )
      fecha_limite = st.date_input("Fecha límite", value=date.today())
    with c2:
      monto_total = st.number_input(
          "Monto Total ($)", min_value=0.0, step=50.0
      )
      monto_pagado = st.number_input(
          "Monto Abonado / Pagado ($)", min_value=0.0, step=50.0
      )
      estado = st.selectbox("Estado", ["Pendiente", "Pagado"])

    guardar_deuda = st.form_submit_button("Guardar Deuda/Préstamo")

  if guardar_deuda:
    if monto_total <= 0:
      st.warning("El monto total debe ser mayor a cero.")
    else:
      sql(
          "INSERT INTO deudas (persona, tipo, monto_total, monto_pagado,"
          " estado, fecha_limite, usuario_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
          [
              persona,
              tipo_deuda,
              float(monto_total),
              float(monto_pagado),
              estado,
              fecha_limite.isoformat(),
              UID,
          ],
      )
      st.success("¡Deuda registrada correctamente!")
      st.rerun()

  df_deudas = sql(
      "SELECT id, persona, tipo, monto_total, monto_pagado, estado,"
      " fecha_limite FROM deudas WHERE usuario_id = ? ORDER BY fecha_limite DESC",
      [UID],
  )

  st.subheader("Historial de Deudas y Préstamos")
  if df_deudas.empty:
    st.info("No tienes deudas o préstamos registrados.")
  else:
    st.dataframe(df_deudas, hide_index=True, use_container_width=True)

    with st.expander("✏️ Editar o 🗑️ Borrar una Deuda"):
      id_deuda_sel = st.number_input(
          "Ingresa el ID de la deuda a modificar/borrar",
          min_value=1,
          step=1,
          key="input_edit_deuda",
      )

      deuda_encontrada = sql(
          "SELECT persona, tipo, monto_total, monto_pagado, estado FROM deudas"
          " WHERE id = ? AND usuario_id = ?",
          [int(id_deuda_sel), UID],
      )

      if not deuda_encontrada.empty:
        p_act = deuda_encontrada.loc[0, "persona"]
        mt_act = float(deuda_encontrada.loc[0, "monto_total"])
        mp_act = float(deuda_encontrada.loc[0, "monto_pagado"])
        e_act = deuda_encontrada.loc[0, "estado"]

        with st.form("form_editar_deuda"):
          st.write(f"Editando la deuda con ID: **{id_deuda_sel}**")
          nueva_persona = st.text_input(
              "Persona o Entidad", value=str(p_act)
          )
          nuevo_monto_t = st.number_input(
              "Nuevo Monto Total ($)", value=mt_act, min_value=0.0
          )
          nuevo_monto_p = st.number_input(
              "Nuevo Monto Abonado ($)", value=mp_act, min_value=0.0
          )
          nuevo_estado = st.selectbox(
              "Nuevo Estado",
              ["Pendiente", "Pagado"],
              index=0 if e_act == "Pendiente" else 1,
          )
          actualizar_deuda_btn = st.form_submit_button("Guardar cambios 💾")

          if actualizar_deuda_btn:
            sql(
                "UPDATE deudas SET persona = ?, monto_total = ?, monto_pagado ="
                " ?, estado = ? WHERE id = ? AND usuario_id = ?",
                [
                    nueva_persona,
                    float(nuevo_monto_t),
                    float(nuevo_monto_p),
                    nuevo_estado,
                    int(id_deuda_sel),
                    UID,
                ],
            )
            st.success("¡Deuda actualizada con éxito!")
            st.rerun()

        if st.button("Eliminar esta deuda 🗑️", key="btn_del_deuda"):
          sql(
              "DELETE FROM deudas WHERE id = ? AND usuario_id = ?",
              [int(id_deuda_sel), UID],
          )
          st.success("Deuda eliminada correctamente.")
          st.rerun()
      else:
        st.info(
            "Ingresa un ID válido de la lista superior para editar o borrar."
        )

# ==================== APARTADO: METAS DE AHORRO ====================
elif menu == "🎯 Metas de Ahorro":
  st.header("🎯 Metas y Objetivos de Ahorro")

  with st.form("nueva_meta", clear_on_submit=True):
    c1, c2 = st.columns(2)
    with c1:
      titulo_meta = st.text_input(
          "Nombre de la Meta", placeholder="Ej. Viaje, Laptop nueva, Colchón"
      )
      monto_objetivo = st.number_input(
          "Monto Objetivo ($)", min_value=1.0, step=100.0
      )
    with c2:
      monto_actual = st.number_input(
          "Dinero ahorrado actualmente ($)", min_value=0.0, step=50.0
      )
      fecha_limite_meta = st.date_input(
          "Fecha límite estimada", value=date.today()
      )

    guardar_meta = st.form_submit_button("Crear Meta de Ahorro 🚀")

  if guardar_meta:
    if monto_objetivo <= 0:
      st.warning("El monto objetivo debe ser mayor a cero.")
    else:
      sql(
          "INSERT INTO metas (titulo, monto_objetivo, monto_actual,"
          " fecha_limite, usuario_id) VALUES (?, ?, ?, ?, ?)",
          [
              titulo_meta,
              float(monto_objetivo),
              float(monto_actual),
              fecha_limite_meta.isoformat(),
              UID,
          ],
      )
      st.success("¡Meta de ahorro creada con éxito!")
      st.rerun()

  df_metas = sql(
      "SELECT id, titulo, monto_objetivo, monto_actual, fecha_limite FROM metas"
      " WHERE usuario_id = ? ORDER BY id DESC",
      [UID],
  )

  st.subheader("Tus Metas Activas")
  if df_metas.empty:
    st.info("Aún no tienes metas de ahorro registradas. ¡Crea una arriba!")
  else:
    for index, row in df_metas.iterrows():
      m_id = int(row["id"])
      titulo = row["titulo"]
      objetivo = float(row["monto_objetivo"])
      actual = float(row["monto_actual"])
      f_limite = row["fecha_limite"]

      porcentaje = min(actual / objetivo, 1.0) if objetivo > 0 else 0.0
      porcentaje_txt = (actual / objetivo) * 100 if objetivo > 0 else 0.0

      st.markdown(f"### 🎯 ID [{m_id}] - {titulo}")
      col_p1, col_p2 = st.columns([3, 1])
      with col_p1:
        st.progress(
            porcentaje,
            text=f"Ahorrado: ${actual:,.2f} de ${objetivo:,.2f} ({porcentaje_txt:.1f}%)",
        )
      with col_p2:
        st.write(f"📅 Meta: {f_limite}")
      st.markdown("---")

    st.subheader("Historial y Gestión de Metas")
    st.dataframe(df_metas, hide_index=True, use_container_width=True)

    with st.expander("✏️ Editar o 🗑️ Borrar una Meta"):
      id_meta_sel = st.number_input(
          "Ingresa el ID de la meta a modificar/borrar",
          min_value=1,
          step=1,
          key="input_edit_meta",
      )

      meta_encontrada = sql(
          "SELECT titulo, monto_objetivo, monto_actual FROM metas WHERE id = ?"
          " AND usuario_id = ?",
          [int(id_meta_sel), UID],
      )

      if not meta_encontrada.empty:
        tit_act = meta_encontrada.loc[0, "titulo"]
        mo_act = float(meta_encontrada.loc[0, "monto_objetivo"])
        ma_act = float(meta_encontrada.loc[0, "monto_actual"])

        with st.form("form_editar_meta"):
          st.write(f"Editando la meta con ID: **{id_meta_sel}**")
          nuevo_tit = st.text_input("Nuevo Nombre", value=str(tit_act))
          nuevo_obj = st.number_input(
              "Nuevo Monto Objetivo ($)", value=mo_act, min_value=1.0
          )
          nuevo_act = st.number_input(
              "Nuevo Monto Ahorrado ($)", value=ma_act, min_value=0.0
          )
          actualizar_meta_btn = st.form_submit_button("Guardar cambios 💾")

          if actualizar_meta_btn:
            sql(
                "UPDATE metas SET titulo = ?, monto_objetivo = ?, monto_actual ="
                " ? WHERE id = ? AND usuario_id = ?",
                [
                    nuevo_tit,
                    float(nuevo_obj),
                    float(nuevo_act),
                    int(id_meta_sel),
                    UID,
                ],
            )
            st.success("¡Meta actualizada con éxito!")
            st.rerun()

        if st.button("Eliminar esta meta 🗑️", key="btn_del_meta"):
          sql(
              "DELETE FROM metas WHERE id = ? AND usuario_id = ?",
              [int(id_meta_sel), UID],
          )
          st.success("Meta eliminada correctamente.")
          st.rerun()
      else:
        st.info(
            "Ingresa un ID válido de la lista superior para editar o borrar."
        )

# ==================== APARTADO: PRESUPUESTO MENSUAL (NUEVO) ====================
elif menu == "📊 Presupuesto Mensual":
  st.header("📊 Presupuesto Mensual")
  st.write("Planifica tus gastos y controla tu presupuesto por mes.")

  # Obtener gastos para calcular los meses disponibles
  df_g = sql(
      "SELECT fecha, categoria, monto FROM gastos WHERE usuario_id = ?", [UID]
  )

  if df_g.empty:
    st.info(
        "Aún no tienes gastos registrados. Registra algunos gastos primero para"
        " ver tu presupuesto."
    )
  else:
    df_g["fecha"] = pd.to_datetime(df_g["fecha"])
    df_g["mes_año"] = df_g["fecha"].dt.to_period("M").astype(str)
    meses_disp = sorted(df_g["mes_año"].unique(), reverse=True)

    c_sel1, c_sel2 = st.columns([2, 2])
    with c_sel1:
      mes_p = st.selectbox(
          "Selecciona el mes a presupuestar:", meses_disp, key="mes_presupuesto"
      )

    # Buscar si ya existe un presupuesto guardado para este mes
    p_actual_db = sql(
        "SELECT monto_limite FROM presupuestos WHERE mes_año = ? AND usuario_id"
        " = ?",
        [mes_p, UID],
    )
    presupuesto_guardado = (
        float(p_actual_db.loc[0, "monto_limite"])
        if not p_actual_db.empty
        else 10000.0
    )

    with c_sel2:
      with st.form("form_editar_presupuesto"):
        nuevo_limite = st.number_input(
            "Presupuesto Total ($)",
            value=presupuesto_guardado,
            min_value=0.0,
            step=100.0,
        )
        guardar_presup = st.form_submit_button("💾 Guardar / Actualizar Límite")

      if guardar_presup:
        # Upsert en SQLite/Turso
        sql(
            "INSERT INTO presupuestos (mes_año, monto_limite, usuario_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(mes_año, usuario_id) DO UPDATE SET monto_limite = ?",
            [mes_p, float(nuevo_limite), UID, float(nuevo_limite)],
        )
        st.success(f"¡Presupuesto para {mes_p} actualizado a ${nuevo_limite:,.2f}!")
        st.rerun()

    # Cálculos del mes seleccionado
    df_mes_g = df_g[df_g["mes_año"] == mes_p]
    gastado_mes = df_mes_g["monto"].sum()
    restante_mes = nuevo_limite - gastado_mes
    porcentaje_gastado = (
        min((gastado_mes / nuevo_limite), 1.0) if nuevo_limite > 0 else 0.0
    )
    porcentaje_txt = (
        (gastado_mes / nuevo_limite) * 100 if nuevo_limite > 0 else 0.0
    )

    st.markdown("---")

    # Tarjetas superiores métricas estilo Dashboard
    m1, m2, m3 = st.columns(3)
    with m1:
      st.metric(
          label="💰 Presupuesto Total", value=f"${nuevo_limite:,.2f}"
      )
    with m2:
      st.metric(
          label="📉 Gastado",
          value=f"${gastado_mes:,.2f}",
          delta=f"{porcentaje_txt:.1f}% del total",
          delta_color="inverse",
      )
    with m3:
      st.metric(label="✨ Restante", value=f"${restante_mes:,.2f}")

    st.progress(
        porcentaje_gastado,
        text=f"Progreso del gasto mensual: {porcentaje_txt:.1f}% utilizado",
    )

    st.markdown("---")
    st.subheader("📋 Desglose por Categorías")

    if not df_mes_g.empty:
      cat_resumen = (
          df_mes_g.groupby("categoria")["monto"]
          .sum()
          .reset_index()
          .rename(columns={"monto": "Gasto"})
      )
      cat_resumen["Porcentaje"] = (
          (cat_resumen["Gasto"] / gastado_mes * 100).round(1).astype(str) + "%"
      )

      st.dataframe(cat_resumen, hide_index=True, use_container_width=True)
    else:
      st.info(f"No hay gastos registrados en el mes de {mes_p}.")
