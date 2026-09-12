import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, render_template,
    flash, g, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

APP_SECRET_KEY = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "cambiar-esta-clave")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "inventario.db"))

app = Flask(__name__)
app.secret_key = APP_SECRET_KEY

AREAS = {
    "pyp": "Mantenimiento PyP",
    "mejoras": "Mantenimiento Mejoras",
}


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL CHECK (rol IN ('admin', 'pyp', 'mejoras')),
            activo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS componentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            categoria TEXT,
            ubicacion TEXT,
            area TEXT NOT NULL CHECK (area IN ('pyp', 'mejoras')),
            cantidad INTEGER NOT NULL DEFAULT 0,
            stock_minimo INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS movimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            componente_id INTEGER,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            area TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('ingreso', 'retiro')),
            cantidad INTEGER NOT NULL,
            usuario TEXT NOT NULL,
            fecha TEXT NOT NULL,
            FOREIGN KEY (componente_id) REFERENCES componentes(id)
        );
        """
    )
    # Usuario admin por defecto (idempotente)
    db.execute(
        "INSERT OR IGNORE INTO usuarios (username, password_hash, nombre, rol) "
        "VALUES (?, ?, ?, 'admin')",
        (ADMIN_USER, generate_password_hash(ADMIN_PASSWORD), "Administrador"),
    )
    db.commit()
    db.close()


init_db()


# ---------------------------------------------------------------------------
# Auth y control de acceso
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("rol") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def current_user_area():
    """None => admin (ve todas las áreas). 'pyp' o 'mejoras' => restringido."""
    rol = session.get("rol")
    return None if rol == "admin" else rol


def area_permitida(area):
    """¿El usuario actual puede operar sobre esta área?"""
    u_area = current_user_area()
    return u_area is None or u_area == area


@app.context_processor
def inject_globals():
    return {
        "AREAS": AREAS,
        "session_nombre": session.get("nombre"),
        "session_rol": session.get("rol"),
        "session_user_id": session.get("user_id"),
        "session_area_nombre": AREAS.get(session.get("rol"), "Todas las áreas") if session.get("rol") != "admin" else "Todas las áreas",
    }


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("inicio") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username,)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["nombre"] = user["nombre"]
            session["rol"] = user["rol"]
            next_url = request.args.get("next") or url_for("inicio")
            return redirect(next_url)
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Inicio / Dashboard
# ---------------------------------------------------------------------------

@app.route("/inicio")
@login_required
def inicio():
    return render_template("inicio.html")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    u_area = current_user_area()

    where = "" if u_area is None else "WHERE area = ?"
    params = () if u_area is None else (u_area,)

    total_componentes = db.execute(
        f"SELECT COUNT(*) FROM componentes {where}", params
    ).fetchone()[0]
    total_unidades = db.execute(
        f"SELECT COALESCE(SUM(cantidad), 0) FROM componentes {where}", params
    ).fetchone()[0]
    sin_stock = db.execute(
        f"SELECT COUNT(*) FROM componentes {where}{' AND' if where else 'WHERE'} cantidad <= stock_minimo",
        params,
    ).fetchone()[0]

    hoy = datetime.now().strftime("%Y-%m-%d")
    mov_where = "WHERE fecha LIKE ?" if u_area is None else "WHERE fecha LIKE ? AND area = ?"
    mov_params = (f"{hoy}%",) if u_area is None else (f"{hoy}%", u_area)
    movimientos_hoy = db.execute(
        f"SELECT COUNT(*) FROM movimientos {mov_where}", mov_params
    ).fetchone()[0]

    ultimos_where = "" if u_area is None else "WHERE area = ?"
    ultimos_params = () if u_area is None else (u_area,)
    ultimos_movimientos = db.execute(
        f"SELECT * FROM movimientos {ultimos_where} ORDER BY id DESC LIMIT 10",
        ultimos_params,
    ).fetchall()

    bajo_stock = db.execute(
        f"SELECT * FROM componentes {where}{' AND' if where else 'WHERE'} cantidad <= stock_minimo "
        "ORDER BY nombre LIMIT 10",
        params,
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_componentes=total_componentes,
        total_unidades=total_unidades,
        sin_stock=sin_stock,
        movimientos_hoy=movimientos_hoy,
        ultimos_movimientos=ultimos_movimientos,
        bajo_stock=bajo_stock,
    )


# ---------------------------------------------------------------------------
# Componentes (listado, alta, edición, baja)
# ---------------------------------------------------------------------------

@app.route("/componentes")
@login_required
def componentes_list():
    db = get_db()
    u_area = current_user_area()
    filtro_area = request.args.get("area") if u_area is None else u_area
    q = request.args.get("q", "").strip()

    sql = "SELECT * FROM componentes WHERE 1=1"
    params = []
    if filtro_area in AREAS:
        sql += " AND area = ?"
        params.append(filtro_area)
    if q:
        sql += " AND (codigo LIKE ? OR nombre LIKE ? OR categoria LIKE ? OR ubicacion LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql += " ORDER BY nombre"

    componentes = db.execute(sql, params).fetchall()
    return render_template(
        "componentes_list.html",
        componentes=componentes,
        q=q,
        filtro_area=filtro_area,
    )


@app.route("/componentes/nuevo", methods=["GET", "POST"])
@login_required
def componente_nuevo():
    u_area = current_user_area()
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        categoria = request.form.get("categoria", "").strip()
        ubicacion = request.form.get("ubicacion", "").strip()
        area = u_area or request.form.get("area", "")
        cantidad = request.form.get("cantidad", "0")
        stock_minimo = request.form.get("stock_minimo", "0")

        if not codigo or not nombre or area not in AREAS:
            flash("Código, nombre y área son obligatorios.", "error")
            return render_template("componente_form.html", componente=request.form)
        if not area_permitida(area):
            abort(403)

        db = get_db()
        try:
            db.execute(
                "INSERT INTO componentes (codigo, nombre, descripcion, categoria, ubicacion, "
                "area, cantidad, stock_minimo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (codigo, nombre, descripcion, categoria, ubicacion, area,
                 int(cantidad or 0), int(stock_minimo or 0)),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash(f'Ya existe un componente con el código "{codigo}".', "error")
            return render_template("componente_form.html", componente=request.form)

        flash("Componente creado correctamente.", "success")
        return redirect(url_for("componentes_list"))

    return render_template("componente_form.html", componente=None)


@app.route("/componentes/<int:comp_id>/editar", methods=["GET", "POST"])
@login_required
def componente_editar(comp_id):
    db = get_db()
    componente = db.execute("SELECT * FROM componentes WHERE id = ?", (comp_id,)).fetchone()
    if componente is None:
        abort(404)
    if not area_permitida(componente["area"]):
        abort(403)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        categoria = request.form.get("categoria", "").strip()
        ubicacion = request.form.get("ubicacion", "").strip()
        stock_minimo = request.form.get("stock_minimo", "0")

        if not nombre:
            flash("El nombre es obligatorio.", "error")
            return render_template("componente_form.html", componente=componente, editar=True)

        db.execute(
            "UPDATE componentes SET nombre = ?, descripcion = ?, categoria = ?, "
            "ubicacion = ?, stock_minimo = ? WHERE id = ?",
            (nombre, descripcion, categoria, ubicacion, int(stock_minimo or 0), comp_id),
        )
        db.commit()
        flash("Componente actualizado.", "success")
        return redirect(url_for("componentes_list"))

    return render_template("componente_form.html", componente=componente, editar=True)


@app.route("/componentes/<int:comp_id>/eliminar", methods=["POST"])
@login_required
def componente_eliminar(comp_id):
    db = get_db()
    componente = db.execute("SELECT * FROM componentes WHERE id = ?", (comp_id,)).fetchone()
    if componente is None:
        abort(404)
    if not area_permitida(componente["area"]):
        abort(403)

    db.execute("DELETE FROM componentes WHERE id = ?", (comp_id,))
    db.commit()
    flash("Componente eliminado.", "success")
    return redirect(url_for("componentes_list"))


# ---------------------------------------------------------------------------
# Ingreso / Retiro de stock
# ---------------------------------------------------------------------------

def _componentes_disponibles(area):
    db = get_db()
    if area:
        return db.execute(
            "SELECT * FROM componentes WHERE area = ? ORDER BY nombre", (area,)
        ).fetchall()
    return db.execute("SELECT * FROM componentes ORDER BY area, nombre").fetchall()


@app.route("/ingreso", methods=["GET", "POST"])
@login_required
def ingreso():
    u_area = current_user_area()
    db = get_db()

    if request.method == "POST":
        modo = request.form.get("modo", "existente")
        cantidad = int(request.form.get("cantidad", "0") or 0)
        if cantidad <= 0:
            flash("La cantidad debe ser mayor a 0.", "error")
            return redirect(url_for("ingreso"))

        if modo == "nuevo":
            codigo = request.form.get("codigo", "").strip()
            nombre = request.form.get("nombre", "").strip()
            area = u_area or request.form.get("area", "")
            if not codigo or not nombre or area not in AREAS:
                flash("Código, nombre y área son obligatorios para un componente nuevo.", "error")
                return redirect(url_for("ingreso"))
            if not area_permitida(area):
                abort(403)
            categoria = request.form.get("categoria", "").strip()
            ubicacion = request.form.get("ubicacion", "").strip()
            try:
                cur = db.execute(
                    "INSERT INTO componentes (codigo, nombre, categoria, ubicacion, area, "
                    "cantidad, stock_minimo) VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (codigo, nombre, categoria, ubicacion, area, cantidad),
                )
                componente_id = cur.lastrowid
            except sqlite3.IntegrityError:
                flash(f'Ya existe un componente con el código "{codigo}". Usa "Ingreso a existente".', "error")
                return redirect(url_for("ingreso"))
        else:
            componente_id = request.form.get("componente_id")
            componente = db.execute(
                "SELECT * FROM componentes WHERE id = ?", (componente_id,)
            ).fetchone()
            if componente is None:
                flash("Selecciona un componente válido.", "error")
                return redirect(url_for("ingreso"))
            if not area_permitida(componente["area"]):
                abort(403)
            db.execute(
                "UPDATE componentes SET cantidad = cantidad + ? WHERE id = ?",
                (cantidad, componente_id),
            )
            codigo, nombre, area = componente["codigo"], componente["nombre"], componente["area"]

        db.execute(
            "INSERT INTO movimientos (componente_id, codigo, nombre, area, tipo, cantidad, "
            "usuario, fecha) VALUES (?, ?, ?, ?, 'ingreso', ?, ?, ?)",
            (componente_id, codigo, nombre, area, cantidad, session["username"],
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
        flash(f"Ingreso registrado: +{cantidad} de {nombre}.", "success")
        return redirect(url_for("ingreso"))

    componentes = _componentes_disponibles(u_area)
    return render_template("ingreso.html", componentes=componentes)


@app.route("/retiro", methods=["GET", "POST"])
@login_required
def retiro():
    u_area = current_user_area()
    db = get_db()

    if request.method == "POST":
        componente_id = request.form.get("componente_id")
        cantidad = int(request.form.get("cantidad", "0") or 0)
        componente = db.execute(
            "SELECT * FROM componentes WHERE id = ?", (componente_id,)
        ).fetchone()

        if componente is None:
            flash("Selecciona un componente válido.", "error")
        elif not area_permitida(componente["area"]):
            abort(403)
        elif cantidad <= 0:
            flash("La cantidad debe ser mayor a 0.", "error")
        elif cantidad > componente["cantidad"]:
            flash(
                f'No hay stock suficiente de "{componente["nombre"]}" '
                f'(disponible: {componente["cantidad"]}).', "error"
            )
        else:
            db.execute(
                "UPDATE componentes SET cantidad = cantidad - ? WHERE id = ?",
                (cantidad, componente_id),
            )
            db.execute(
                "INSERT INTO movimientos (componente_id, codigo, nombre, area, tipo, cantidad, "
                "usuario, fecha) VALUES (?, ?, ?, ?, 'retiro', ?, ?, ?)",
                (componente_id, componente["codigo"], componente["nombre"], componente["area"],
                 cantidad, session["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            db.commit()
            flash(f'Retiro registrado: -{cantidad} de {componente["nombre"]}.', "success")
        return redirect(url_for("retiro"))

    componentes = [c for c in _componentes_disponibles(u_area) if c["cantidad"] > 0]
    return render_template("retiro.html", componentes=componentes)


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

@app.route("/buscar")
@login_required
def buscar():
    u_area = current_user_area()
    q = request.args.get("q", "").strip()
    resultados = []
    if q:
        db = get_db()
        sql = ("SELECT * FROM componentes WHERE "
               "(codigo LIKE ? OR nombre LIKE ? OR categoria LIKE ? OR ubicacion LIKE ?)")
        like = f"%{q}%"
        params = [like, like, like, like]
        if u_area is not None:
            sql += " AND area = ?"
            params.append(u_area)
        sql += " ORDER BY nombre"
        resultados = db.execute(sql, params).fetchall()
    return render_template("buscar.html", q=q, resultados=resultados)


# ---------------------------------------------------------------------------
# Administración de usuarios (solo admin)
# ---------------------------------------------------------------------------

@app.route("/admin/usuarios")
@login_required
@admin_required
def usuarios_list():
    db = get_db()
    usuarios = db.execute("SELECT * FROM usuarios ORDER BY rol, username").fetchall()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/admin/usuarios/nuevo", methods=["GET", "POST"])
@login_required
@admin_required
def usuario_nuevo():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "")
        password = request.form.get("password", "")

        if not username or not nombre or rol not in ("admin", "pyp", "mejoras") or not password:
            flash("Todos los campos son obligatorios.", "error")
            return render_template("usuario_form.html", usuario=request.form)

        db = get_db()
        try:
            db.execute(
                "INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), nombre, rol),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash(f'Ya existe un usuario con el nombre de usuario "{username}".', "error")
            return render_template("usuario_form.html", usuario=request.form)

        flash("Usuario creado correctamente.", "success")
        return redirect(url_for("usuarios_list"))

    return render_template("usuario_form.html", usuario=None)


@app.route("/admin/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def usuario_editar(user_id):
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()
    if usuario is None:
        abort(404)

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        rol = request.form.get("rol", "")
        password = request.form.get("password", "").strip()
        activo = 1 if request.form.get("activo") == "on" else 0

        if not nombre or rol not in ("admin", "pyp", "mejoras"):
            flash("Nombre y rol son obligatorios.", "error")
            return render_template("usuario_form.html", usuario=usuario, editar=True)

        if password:
            db.execute(
                "UPDATE usuarios SET nombre = ?, rol = ?, password_hash = ?, activo = ? WHERE id = ?",
                (nombre, rol, generate_password_hash(password), activo, user_id),
            )
        else:
            db.execute(
                "UPDATE usuarios SET nombre = ?, rol = ?, activo = ? WHERE id = ?",
                (nombre, rol, activo, user_id),
            )
        db.commit()
        flash("Usuario actualizado.", "success")
        return redirect(url_for("usuarios_list"))

    return render_template("usuario_form.html", usuario=usuario, editar=True)


@app.route("/admin/usuarios/<int:user_id>/eliminar", methods=["POST"])
@login_required
@admin_required
def usuario_eliminar(user_id):
    if user_id == session.get("user_id"):
        flash("No puedes eliminar tu propio usuario mientras tienes la sesión abierta.", "error")
        return redirect(url_for("usuarios_list"))
    db = get_db()
    db.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    db.commit()
    flash("Usuario eliminado.", "success")
    return redirect(url_for("usuarios_list"))


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", codigo=403,
                            mensaje="No tienes acceso a esta área o sección."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", codigo=404,
                            mensaje="No se encontró lo que buscabas."), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
