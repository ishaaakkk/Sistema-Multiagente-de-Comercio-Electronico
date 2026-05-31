# Demo realmente distribuida

El guión de la práctica (criterio 3.6) exige que el sistema corra en
varias máquinas o contenedores. Toda la infraestructura ya admite este
modo: los agentes Flask pueden escuchar en `0.0.0.0` (`--open`) y se
anuncian al directorio con `--hostaddr`, de modo que las URLs
registradas son accesibles desde el resto de la red.

Hay dos formas de probarlo. La primera, `src/develop.sh`, sigue siendo
el atajo "todo-en-uno" para desarrollo (todos los agentes en la misma
máquina). La segunda, `src/distributed.sh`, lanza **un solo agente** y
está pensada para invocarse desde cada máquina/contenedor.

## 1. `src/develop.sh` parametrizable

`develop.sh` acepta variables de entorno y no usa direcciones
hardcodeadas:

```bash
DIR_HOST=10.0.0.10 DIR_PORT=9000 HOSTADDR=10.0.0.10 bash src/develop.sh
```

Esto arranca todos los agentes anunciándose con la IP indicada y
contactando con el directorio en esa IP/puerto.

## 2. `src/distributed.sh` (un agente por máquina)

Cada máquina lanza el agente que le corresponde:

| Máquina | Comando |
| --- | --- |
| Directorio (10.0.0.10) | `HOSTADDR=10.0.0.10 ./src/distributed.sh directorio 9000` |
| Centro logístico BCN (10.0.0.11) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.11 ./src/distributed.sh cl_bcn 9002` |
| Centro logístico MAD (10.0.0.12) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.12 ./src/distributed.sh cl_mad 9012` |
| Transportista Express (10.0.0.13) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.13 ./src/distributed.sh transportista_express 9003` |
| Transportista Eco (10.0.0.14) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.14 ./src/distributed.sh transportista_eco 9011` |
| Comerciante (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./src/distributed.sh comerciante 9001` |
| Catálogo (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./src/distributed.sh catalogo 9006` |
| Feedback (10.0.0.15) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.15 ./src/distributed.sh feedback 9007` |
| Financiero (10.0.0.16) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.16 ./src/distributed.sh financiero 9005` |
| Proveedor de pagos (10.0.0.16) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.16 ./src/distributed.sh proveedor_pagos 9004` |
| Vendedor externo (10.0.0.17) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.17 ./src/distributed.sh vendedor_externo 9008` |
| Devolución (10.0.0.18) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.18 ./src/distributed.sh devolucion 9009` |
| Asistente / UI (10.0.0.19) | `DIR_HOST=10.0.0.10 HOSTADDR=10.0.0.19 ./src/distributed.sh asistente 9010` |

Después se accede al cliente en `http://10.0.0.19:9010/iface`.

## 3. Despliegue con contenedores

Una alternativa práctica para la demostración en clase es usar Docker
con un *bridge network* compartido. Un `docker-compose.yml` de ejemplo:

```yaml
version: "3.9"
services:
  directorio:
    image: python:3.12-slim
    working_dir: /app/src
    command: bash distributed.sh directorio 9000
    environment:
      - HOSTADDR=directorio
    volumes:
      - ./:/app
    ports: ["9000:9000"]
    networks: [ecsdi]

  cl_bcn:
    image: python:3.12-slim
    working_dir: /app/src
    command: bash distributed.sh cl_bcn 9002
    environment:
      - DIR_HOST=directorio
      - HOSTADDR=cl_bcn
    volumes: [./:/app]
    networks: [ecsdi]

  # …repetir para cada agente…

networks:
  ecsdi:
    driver: bridge
```

> Recordatorio: instala dependencias dentro del contenedor antes de
> ejecutar (`pip install -r src/requirements.txt`) o usa una imagen
> intermedia que las precargue.

## 4. Checklist de cosas que NO deben usar `127.0.0.1`

- `develop.sh` (ya parametrizado) ✔
- `distributed.sh` (lanzamiento por máquina) ✔
- `--open` en todos los agentes (Flask bind 0.0.0.0) ✔
- URLs anunciadas al directorio = `--hostaddr` ✔

Las URLs "fallback" hardcodeadas a `127.0.0.1` que aún aparecen en
`agente_comerciante.py` y en otros agentes solo se usan cuando NO se
pasa `--dir`. En la demo distribuida siempre se arranca con `--dir`,
así que se ignoran.
