---
categoria: guias
tags: produccion, redis, concurrencia, apagado, kubernetes
---
# Despliegue en producción

Esta guía resume las recomendaciones para ejecutar workers de Tasklet en un entorno de producción.

## Broker

Se recomienda Redis con persistencia AOF (`appendonly yes`) activada, para no perder mensajes encolados si el broker se reinicia. Para volúmenes altos o requisitos de entrega más estrictos, RabbitMQ con colas durables es la mejor opción.

## Concurrencia

- Para tareas limitadas por CPU, usá una concurrencia igual a la cantidad de núcleos disponibles.
- Para tareas limitadas por entrada/salida (llamadas HTTP, base de datos) con corrutinas, se puede usar una concurrencia mucho mayor, de 100 o más.
- El parámetro `prefetch_multiplier` (por defecto 4) define cuántas tareas por cada slot de concurrencia descarga el worker por adelantado. Para tareas largas conviene bajarlo a 1, de modo que un worker ocupado no acapare tareas que otro worker libre podría ejecutar.

## Apagado ordenado de un worker

Para detener un worker sin perder las tareas que está ejecutando, enviale la señal `SIGTERM`. Al recibirla, el worker deja de consumir tareas nuevas y espera hasta `shutdown_timeout` segundos (por defecto 60) a que terminen las tareas en curso. Si el tiempo se agota, las tareas pendientes se devuelven al broker.

Si se usa `SIGKILL`, el worker se detiene de inmediato y las tareas en curso se pierden, salvo que la tarea tenga `acks_late=True`: en ese caso la confirmación se envía recién al terminar la ejecución, y el broker reencola la tarea si el worker muere antes.

## Kubernetes

El valor de `terminationGracePeriodSeconds` del pod debe ser mayor que `shutdown_timeout`; de lo contrario, Kubernetes enviará `SIGKILL` antes de que el worker termine el apagado ordenado. Para los chequeos de salud, iniciá el worker con `--health-port 8080` y apuntá la sonda de liveness a `/healthz`.

## Monitoreo

Con el extra `tasklet[metrics]` instalado, el worker expone métricas Prometheus en `/metrics`: tareas ejecutadas, fallidas, reintentadas y latencia de la cola. Configurá alertas sobre la profundidad de la cola y sobre la tasa de tareas fallidas.
