---
categoria: guias
tags: instalacion, pip, extras, requisitos
---
# Instalación de Tasklet

Tasklet es una librería de Python para ejecutar tareas en segundo plano mediante colas asíncronas. Esta guía explica cómo instalarla y cómo elegir los extras correctos según el broker que vayas a usar.

## Requisitos

- Python 3.10 o superior (se recomienda 3.12).
- Un broker de mensajes accesible por red: Redis 6+ o RabbitMQ 3.9+.
- Sistema operativo Linux, macOS o Windows. En Windows se recomienda usar WSL2 para los workers.

## Instalación básica

```bash
pip install tasklet
```

La instalación básica incluye el núcleo, el CLI (`tasklet worker`, `tasklet beat`) y el serializador JSON. No incluye ningún cliente de broker, por eso hay que instalar al menos un extra.

## Extras disponibles

Los extras se instalan entre corchetes. Los más usados son:

- `tasklet[redis]`: instala el cliente de Redis y habilita `broker_url="redis://..."`.
- `tasklet[amqp]`: instala el cliente AMQP para usar RabbitMQ como broker.
- `tasklet[metrics]`: expone métricas en formato Prometheus.
- `tasklet[msgpack]`: agrega el serializador MessagePack.

Para combinar varios extras en un solo comando:

```bash
pip install "tasklet[redis,metrics]"
```

Si vas a usar Redis como broker, el extra que necesitás es `tasklet[redis]`.

## Verificar la instalación

```bash
python -m tasklet --version
```

Si el comando imprime el número de versión, la instalación es correcta.

## Problemas frecuentes

- `ImportError: No module named 'redis'`: falta el extra `redis`. Ejecutá `pip install "tasklet[redis]"` dentro del mismo entorno virtual donde corre el worker.
- `command not found: tasklet`: el entorno virtual no está activado o el directorio de scripts no está en el `PATH`.
- Conflictos de versiones: instalá Tasklet en un entorno virtual limpio para evitar choques con otras dependencias.
