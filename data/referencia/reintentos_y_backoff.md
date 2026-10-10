---
categoria: referencia
tags: reintentos, backoff, resiliencia, dlq
---
# Reintentos y espera exponencial (backoff)

Tasklet puede reintentar automáticamente las tareas que fallan. La política de reintentos se configura por tarea en el decorador `@app.task` o de forma global en la aplicación.

## Parámetros de la política de reintentos

- `max_retries` (por defecto 3): cantidad máxima de reintentos después del primer intento fallido. Con valor 0 se desactivan los reintentos.
- `backoff_factor` (por defecto 2.0): factor de la espera exponencial. La espera antes del intento número `n` es `backoff_factor ** n` segundos. Con `backoff_factor=2.0` las esperas son 2, 4, 8, 16 segundos.
- `backoff_max` (por defecto 300): tope en segundos para la espera entre reintentos.
- `jitter` (por defecto `True`): agrega una variación aleatoria a cada espera para evitar que muchos reintentos se disparen al mismo tiempo.
- `retry_on`: tupla de excepciones que disparan un reintento. Si no se define, se reintenta ante cualquier excepción.
- `retry_exclude`: tupla de excepciones que nunca se reintentan, por ejemplo errores de validación.

## Ejemplo

```python
@app.task(
    max_retries=5,
    backoff_factor=1.5,
    retry_on=(ConnectionError, TimeoutError),
)
async def sincronizar_inventario(sucursal_id: int):
    ...
```

En este ejemplo la tarea se reintenta hasta 5 veces, solo ante errores de conexión o timeout, con una espera que crece por un factor de 1.5.

## Reintento manual

Dentro de una tarea se puede pedir un reintento explícito con una espera fija:

```python
raise self.retry(countdown=30)
```

El parámetro `countdown` indica cuántos segundos esperar antes del próximo intento y reemplaza al cálculo exponencial para ese intento.

## Cola de mensajes muertos (DLQ)

Cuando una tarea agota todos sus reintentos, se mueve a la cola `tasklet.dlq` (dead-letter queue) junto con la excepción original y el historial de intentos. Las tareas en la DLQ no se vuelven a ejecutar solas: hay que revisarlas y reenviarlas con `tasklet dlq replay`.

## Recomendación de diseño

Escribí las tareas de forma idempotente: si una tarea se ejecuta dos veces por un reintento, el resultado final debe ser el mismo que si se ejecutara una sola vez.
