---
categoria: guias
tags: tutorial, tareas, worker, resultados
---
# Primeros pasos con Tasklet

Este tutorial muestra cómo definir una tarea, encolarla y ejecutarla con un worker.

## 1. Crear la aplicación

```python
from tasklet import Tasklet

app = Tasklet(broker_url="redis://localhost:6379/0")
```

El objeto `app` es el punto central: registra las tareas y mantiene la conexión con el broker.

## 2. Definir una tarea

Una tarea es una función decorada con `@app.task`:

```python
@app.task
async def enviar_correo(destinatario: str, asunto: str) -> bool:
    ...
    return True
```

Las tareas pueden ser funciones normales o corrutinas (`async def`). Las corrutinas se ejecutan directamente en el event loop del worker.

## 3. Encolar una tarea

```python
resultado = enviar_correo.delay("ana@example.com", "Bienvenida")
```

El método `.delay()` envía la tarea al broker y devuelve inmediatamente un objeto `AsyncResult`. Para más control se puede usar `.enqueue(args=..., eta=...)`, que permite programar la ejecución para una fecha futura.

## 4. Ejecutar un worker

```bash
tasklet worker --app mi_proyecto:app --concurrency 4
```

El parámetro `--app` indica el módulo y el nombre de la variable de la aplicación. El parámetro `--concurrency` define cuántas tareas puede ejecutar el worker en paralelo.

## 5. Consultar el resultado

```python
valor = resultado.get(timeout=10)
```

`AsyncResult.get()` bloquea hasta que la tarea termina o se agota el timeout. Los estados posibles de una tarea son `PENDING`, `RUNNING`, `SUCCESS` y `FAILED`. Para guardar resultados hay que configurar un result backend (`result_backend="redis://..."`); sin backend, `get()` lanza una excepción.
