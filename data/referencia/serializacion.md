---
categoria: referencia
tags: serializacion, json, pickle, msgpack
---
# Serialización de argumentos y resultados

Los argumentos de una tarea y sus resultados viajan por el broker, por lo que deben convertirse a bytes. Esa conversión la hace un serializador, que se elige con el parámetro `serializer` de la aplicación.

## Serializadores disponibles

- `json` (por defecto): legible y seguro. Solo admite tipos básicos: cadenas, números, booleanos, listas, diccionarios y `None`.
- `msgpack`: formato binario más compacto y rápido. Requiere el extra `tasklet[msgpack]`.
- `pickle`: admite casi cualquier objeto de Python, pero es inseguro si el broker no es de confianza, porque deserializar datos manipulados puede ejecutar código arbitrario. No se recomienda en producción.

## Cómo configurarlo

```python
app = Tasklet(
    broker_url="redis://localhost:6379/0",
    serializer="msgpack",
)
```

El serializador también se puede definir por tarea:

```python
@app.task(serializer="json")
async def procesar_pedido(pedido: dict): ...
```

## Fechas, decimales y objetos propios

El serializador JSON no entiende `datetime` ni `Decimal`. Hay dos opciones: convertir los valores a cadenas antes de encolar la tarea (por ejemplo con `fecha.isoformat()`), o registrar un codificador personalizado con `app.register_encoder(tipo, codificar, decodificar)`.

## Buenas prácticas

Pasá identificadores en lugar de objetos completos. En vez de enviar un objeto de usuario entero, enviá `usuario_id` y cargá el objeto desde la base de datos dentro de la tarea. Así los mensajes quedan pequeños y los datos siempre están actualizados al momento de ejecutar.
