import io
import sys
from contextlib import redirect_stdout
from datetime import date, timedelta

import yaml
from nicegui import ui
from nicegui.events import UploadEventArguments
import tempfile
import os

# Importa tus módulos existentes
from calendar_manager import CalendarManager
from orders_parser import parse_orders
from planner_engine import plan_full_order
from reports import get_weekly_report_data, get_weekly_resource_usage_data, get_weekly_orders_summary_data
from resource_manager import ResourceManager, load_resource_config

# --- Estado de la Aplicación ---
# Usaremos un diccionario para mantener el estado global de la aplicación
APP_STATE = {
    "orders": [],
    "holidays": set(),
    "resources_cfg": {},
    "resource_manager": None,
    "calendar_manager": None,
    "full_plan": {},
    "report_output": "",
}

# --- Funciones de Lógica ---

def load_orders_from_file(filename="orders.yaml"):
    """Carga las órdenes y actualiza el estado y la UI."""
    try:
        APP_STATE["orders"] = parse_orders(filename)
        ui.notify(f"Órdenes cargadas correctamente desde {filename}", color="positive")
        # Actualiza la tabla en la UI
        orders_table.rows = [order.__dict__ for order in APP_STATE["orders"]]
        orders_table.update()
    except Exception as e:
        ui.notify(f"Error al cargar órdenes: {e}", color="negative")

def load_resources_from_file(filename="resources.yaml"):
    """Carga la configuración de recursos y actualiza el estado y la UI."""
    try:
        with open(filename, 'r') as f:
            cfg = yaml.safe_load(f)
        APP_STATE["resources_cfg"] = cfg
        APP_STATE["resource_manager"] = load_resource_config(filename)
        ui.notify("Recursos cargados desde resources.yaml", color="positive")
        # Actualiza los campos en la UI
        update_resources_ui_from_state()
    except Exception as e:
        ui.notify(f"Error al cargar recursos: {e}", color="negative")

def save_resources_to_file():
    """Guarda la configuración de recursos de la UI al archivo."""
    try:
        # Recolecta los valores de la UI en el estado
        update_state_from_resources_ui()
        with open("resources.yaml", 'w') as f:
            yaml.dump(APP_STATE["resources_cfg"], f, default_flow_style=False, sort_keys=False)
        ui.notify("Recursos guardados en resources.yaml", color="positive")
    except Exception as e:
        ui.notify(f"Error al guardar recursos: {e}", color="negative")

def load_holidays_from_file():
    """Carga los feriados y actualiza el estado y la UI."""
    try:
        APP_STATE["calendar_manager"] = CalendarManager("holidays.yaml")
        APP_STATE["holidays"] = APP_STATE["calendar_manager"].holidays
        ui.notify("Feriados cargados desde holidays.yaml", color="positive")
        # Actualiza la lista en la UI
        holidays_list.clear()
        with holidays_list:
            for holiday in sorted(list(APP_STATE["holidays"])):
                ui.label(holiday.isoformat())
        holidays_list.update()
    except Exception as e:
        ui.notify(f"Error al cargar feriados: {e}", color="negative")

def run_planner():
    """Ejecuta el planificador con la configuración y datos actuales."""
    if not APP_STATE["orders"]:
        ui.notify("Por favor, carga las órdenes primero.", color="warning")
        return
    
    if not APP_STATE["resource_manager"]:
        ui.notify("Por favor, carga los recursos primero.", color="warning")
        return
    
    if not APP_STATE["calendar_manager"]:
        ui.notify("Por favor, carga los feriados primero.", color="warning")
        return

    try:
        # Ordena las órdenes por dias hasta la fecha de entrega menos la duración estimada
        orders_to_plan = sorted(
            APP_STATE["orders"],
            key=lambda o: (
                (o.due_date - timedelta(days=o.compute_estimated_duration(APP_STATE["resource_manager"].max_molds_per_day))) - date.today()
            ).days
        )

        # 3. Planifica
        full_plan = {}
        for order in orders_to_plan:
            plan = plan_full_order(order, APP_STATE["calendar_manager"], APP_STATE["resource_manager"])
            full_plan[order.order_id] = {
                "status": plan["status"].name,
                "start_date": plan["start_date"].isoformat() if plan["start_date"] else None,
                "end_date": plan["end_date"].isoformat() if plan["end_date"] else None,
                "schedule": {
                    phase: [(d.isoformat(), v) for d, v in phase_data]
                    for phase, phase_data in plan["schedule"].items()
                }
            }
        APP_STATE["full_plan"] = full_plan
        ui.notify("Planificación completada.", color="positive")
        
        # 4. Actualiza la UI
        report_data = get_weekly_report_data(APP_STATE["full_plan"], orders_to_plan, APP_STATE["resource_manager"])

        # Crea la tabla NiceGUI usando report_data
        resource_data = get_weekly_resource_usage_data(APP_STATE["resource_manager"])
        resource_table.columns = [{"name": col, "label": col, "field": col} for col in resource_data["columns"]]
        resource_table.rows = [
            {resource_data["columns"][i]: cell for i, cell in enumerate(row)}
            for row in resource_data["rows"]
        ]
        resource_table.update()

        orders_data = get_weekly_orders_summary_data(APP_STATE["full_plan"], orders_to_plan, APP_STATE["resource_manager"])
        orders_table.columns = [{"name": col, "label": col, "field": col} for col in orders_data["columns"]]
        orders_table.rows = [
            {orders_data["columns"][i]: cell for i, cell in enumerate(row)}
            for row in orders_data["rows"]
        ]
        orders_table.update()

    except Exception as e:
        ui.notify(f"Error durante la planificación: {e}", color="negative")
        print(e) # Para depuración en la consola





# --- Definición de la Interfaz de Usuario ---
with ui.tabs().classes('w-full') as tabs:
    orders_tab = ui.tab('Órdenes de Produccion')
    resources_tab = ui.tab('Configuracion')
    holidays_tab = ui.tab('Calendario')
    planner_tab = ui.tab('Plan')

def handle_orders_upload(e: UploadEventArguments):
            """Guarda el archivo de órdenes subido en una ubicación temporal y lo procesa."""
            temp_filepath = None
            try:
                # Crea un archivo temporal para guardar el contenido subido
                with tempfile.NamedTemporaryFile(delete=False, suffix='.yaml', mode='w', encoding='utf-8') as tmp:
                    content = e.content.read().decode('utf-8')
                    tmp.write(content)
                    temp_filepath = tmp.name
                
                # Carga las órdenes desde el archivo temporal
                APP_STATE["orders"] = parse_orders(temp_filepath)
                ui.notify(f"Órdenes cargadas desde '{e.name}'", color="positive")
                
                # Prepara los datos para la tabla, convirtiendo Enums a strings
                rows = []
                for order in APP_STATE["orders"]:
                    row_data = {
                                    'order_type': getattr(order, 'order_type', ''),
                                    'order_id': getattr(order, 'order_id', ''),
                                    'part_number': getattr(order, 'part_number', ''),
                                    'product_family': getattr(order, 'product_family', ''),
                                    'quantity': getattr(order, 'parts_total', ''),
                                    'due_date': getattr(order, 'due_date', ''),
                                }
                    rows.append(row_data)
                
                orders_table.rows = rows
                orders_table.update()

            except Exception as ex:
                ui.notify(f"Error al cargar el archivo de órdenes: {ex}", color="negative")
            finally:
                # Limpia el archivo temporal después de usarlo
                if temp_filepath and os.path.exists(temp_filepath):
                    os.remove(temp_filepath)


with ui.tab_panels(tabs, value=orders_tab).classes('w-full'):
    # Panel de Órdenes
    with ui.tab_panel(orders_tab):
        ui.upload(label='Seleccionar archivo de órdenes', on_upload=handle_orders_upload, auto_upload=True).props('accept=.yaml,.yml')
        orders_table = ui.table(
            columns=[
                {'name': 'order_type', 'label': 'Tipo', 'field': 'order_type'},
                {'name': 'order_id', 'label': 'ID', 'field': 'order_id'},
                {'name': 'part_number', 'label': 'Part Number', 'field': 'part_number'},
                {'name': 'product_family', 'label': 'Familia', 'field': 'product_family'},
                {'name': 'quantity', 'label': 'Cantidad', 'field': 'quantity'},
                {'name': 'due_date', 'label': 'Fecha Entrega', 'field': 'due_date'},
            ],
            rows=[],
            row_key='order_id'
        ).classes('w-full')

    # Panel de Configuracion
    with ui.tab_panel(resources_tab):
        ui.label('Configuración').classes('text-h5')
        with ui.row():
            ui.button('Cargar desde resources.yaml', on_click=load_resources_from_file)
            ui.button('Guardar en resources.yaml', on_click=save_resources_to_file)

        with ui.grid(columns=2):
            # Los inputs se crearán dinámicamente
            resources_container = ui.element('div')

        def update_resources_ui_from_state():
            """Limpia y rellena la UI de recursos desde el estado."""
            resources_container.clear()
            with resources_container:
                for key, value in APP_STATE["resources_cfg"].items():
                    if isinstance(value, dict):
                        with ui.card().classes('w-full'):
                            ui.label(key.replace('_', ' ').title()).classes('text-bold')
                            for sub_key, sub_value in value.items():
                                ui.input(label=sub_key, value=str(sub_value)).bind_value(APP_STATE["resources_cfg"][key], sub_key)
                    else:
                        ui.number(label=key.replace('_', ' ').title(), value=value).bind_value(APP_STATE["resources_cfg"], key)
        
        def update_state_from_resources_ui():
            """Función placeholder, ya que el binding es bidireccional."""
            # Con nicegui, el binding actualiza APP_STATE automáticamente.
            # Podríamos añadir validaciones aquí si fuera necesario.
            pass

    # Calendario de Feriados
    with ui.tab_panel(holidays_tab):
        ui.label('Calendario').classes('text-h5')
        ui.button('Cargar Feriados desde holidays.yaml', on_click=load_holidays_from_file)
        holidays_list = ui.column()

    # Panel del Planificador
    with ui.tab_panel(planner_tab):
        ui.label('Planificador').classes('text-h5')
        ui.button('Planificar Ordenes', on_click=run_planner)
        ui.label('Uso de Recursos por Semana').classes('text-h6 mt-4')
        resource_table = ui.table(columns=[], rows=[]).classes('w-full dense')
        ui.label('Resumen Semanal de Órdenes').classes('text-h6 mt-4')
        orders_table = ui.table(columns=[], rows=[]).classes('w-full dense')

# Carga inicial al arrancar la app
load_resources_from_file()

ui.run()
