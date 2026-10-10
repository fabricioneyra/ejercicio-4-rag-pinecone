---
categoria: errores
tags: errores, diagnostico, codigos, heartbeat
---
# Códigos de error de Tasklet

Todos los errores de Tasklet incluyen un código con el formato `E` seguido de cuatro dígitos. El primer dígito indica la familia: 1 para conexión y transporte, 2 para registro de tareas, 3 para resultados, 4 para workers y 5 para colas internas.

## E1001: BrokerConnectionError

El proceso no pudo conectarse al broker. Revisá que `broker_url` sea correcto, que el broker esté activo y que ningún firewall bloquee el puerto (6379 para Redis, 5672 para RabbitMQ). Tasklet reintenta la conexión cada 5 segundos; el parámetro `broker_connection_retry_max` define cuántas veces antes de abandonar.

## E1004: SerializationError

Uno de los argumentos de la tarea no se pudo serializar con el serializador configurado. Es frecuente al pasar objetos `datetime`, `Decimal` o instancias de clases propias con el serializador JSON. Convertí los valores a tipos básicos antes de encolar la tarea o registrá un codificador personalizado.

## E2010: TaskNotRegistered

El worker recibió una tarea que no conoce. Ocurre cuando el módulo donde se define la tarea no fue importado por el worker. Agregá el módulo a la opción `imports` de la aplicación y reiniciá el worker.

## E3007: ResultExpired

Se consultó el resultado de una tarea cuyo tiempo de vida en el result backend ya venció. El valor por defecto de `result_ttl` es 3600 segundos. Aumentá `result_ttl` si necesitás conservar los resultados por más tiempo.

## E4021: WorkerHeartbeatLost

El broker dejó de recibir heartbeats de un worker durante más de `heartbeat_timeout` segundos (por defecto 30). Cuando esto ocurre, el broker considera que el worker murió y vuelve a encolar sus tareas en curso, lo que puede provocar que una tarea se ejecute dos veces.

Causas habituales:

- Código síncrono que bloquea el event loop del worker durante más tiempo que `heartbeat_timeout`, por ejemplo una consulta pesada o un `time.sleep()` dentro de una corrutina.
- Falta de CPU o memoria en el contenedor, con el proceso suspendido por el sistema operativo.
- Pausas largas del recolector de basura con muchos objetos en memoria.

Cómo solucionarlo:

- Mover el trabajo bloqueante fuera del event loop con `await loop.run_in_executor(None, funcion_bloqueante)`.
- Aumentar `heartbeat_timeout` si las tareas tienen pausas legítimas largas.
- Asignar más recursos al worker y reducir `--concurrency`.
- Escribir las tareas de forma idempotente, porque una tarea reencolada puede ejecutarse más de una vez.

## E4030: ConcurrencyLimitExceeded

Se intentó ejecutar más tareas simultáneas que el límite `--concurrency` del worker o que el límite por tarea definido con `max_concurrency`. La tarea queda en espera hasta que se libere un lugar; no se pierde.

## E5003: DeadLetterOverflow

La cola de mensajes muertos `tasklet.dlq` superó el tamaño máximo definido en `dlq_max_size` (por defecto 10000). Los mensajes más antiguos se descartan para dejar lugar a los nuevos. Revisá y reenviá las tareas de la DLQ con `tasklet dlq replay`, o aumentá `dlq_max_size`.
