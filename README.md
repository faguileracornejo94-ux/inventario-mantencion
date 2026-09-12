# Inventario Bodega

Aplicación web para el control de inventario de componentes menores en bodega, con dos áreas independientes:

- **Mantenimiento PyP**
- **Mantenimiento Mejoras**

## Control de acceso

- **Administrador**: ve y gestiona ambas áreas, además de los usuarios del sistema.
- **Usuario de área** (`pyp` o `mejoras`): solo ve y gestiona los componentes y movimientos de su propia área. No puede ver ni modificar la otra área.

## Funciones

- Login por usuario/contraseña.
- Listado y búsqueda de componentes (código, nombre, categoría, ubicación en bodega).
- Ingreso de stock (a un componente existente o creando uno nuevo).
- Retiro de stock, con validación de stock disponible.
- Historial de movimientos (ingresos/retiros) con usuario y fecha.
- Dashboard con totales, unidades, componentes bajo stock mínimo y últimos movimientos.
- Administración de usuarios (solo administrador): crear, editar rol/área, activar/desactivar.

## Ejecutar localmente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ADMIN_USER=admin
export ADMIN_PASSWORD="cambia-esta-clave"
export APP_SECRET_KEY="una-clave-secreta-larga"

python app.py
```

La app queda disponible en `http://localhost:5000`. El usuario administrador se crea automáticamente
al iniciar, con las credenciales de las variables de entorno `ADMIN_USER` / `ADMIN_PASSWORD`.

Desde el panel de **Usuarios** (como administrador) puedes crear el resto de las cuentas y asignarles
el área (Mantenimiento PyP o Mantenimiento Mejoras).

## Variables de entorno

| Variable         | Descripción                                    | Default                  |
|------------------|-------------------------------------------------|---------------------------|
| `ADMIN_USER`     | Usuario administrador inicial                   | `admin`                   |
| `ADMIN_PASSWORD` | Contraseña del administrador inicial            | `cambiar-esta-clave`      |
| `APP_SECRET_KEY` | Clave secreta de sesión de Flask                | `dev-secret-change-me`    |
| `DB_PATH`        | Ruta del archivo SQLite                         | `inventario.db` (local)   |
| `PORT`           | Puerto en el que corre la app (modo desarrollo) | `5000`                    |

## Despliegue

Pensada para desplegarse igual que otras apps Flask sencillas (por ejemplo DigitalOcean App Platform):
usa `gunicorn app:app` como comando de arranque (ver `Procfile`) e instala `requirements.txt`.

**Importante:** si el hosting usa almacenamiento efímero (como App Platform sin volumen ni base de datos
gestionada), la base SQLite se reinicia en cada redeploy. Para datos persistentes en producción, usar un
volumen persistente o una base de datos gestionada.
