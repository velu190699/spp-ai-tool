# SPP Market Intelligence Agent — Script de Presentación

---

## INTRODUCCIÓN

Hoy les presento el SPP Market Intelligence Agent, una herramienta que automatiza el monitoreo de cambios regulatorios en el mercado SPP.

El problema que resuelve es simple: hoy alguien del equipo tiene que entrar manualmente a SPP.org cada mes, descargar documentos, revisarlos, identificar qué cambios vienen y notificar al equipo. Eso toma horas. Este agente lo hace solo.

El flujo tiene 5 fases. De esas 5, tenemos 3 completamente implementadas y funcionando hoy. Las otras 2 están en progreso.

---

## FASE 1 — TRIGGER

La primera fase es el trigger: cómo arranca el agente sin que nadie lo inicie manualmente.

Usamos Windows Task Scheduler. Creamos un archivo batch llamado `run_agent.bat` que el scheduler ejecuta automáticamente en la fecha que configuremos — mensual, trimestral, lo que necesitemos.

Una cosa importante que resolvimos: si la computadora estaba apagada el día programado, el agente corre en el próximo arranque. Y si no hay conexión a internet, espera — no tiene sentido correr sin poder descargar nada.

**Estado: completamente implementado y funcionando.**

---

## FASE 2 — WEB SCRAPING

La segunda fase descarga 4 documentos de SPP.org:

- El RR Master List, que es un Excel con todos los cambios propuestos
- Los materiales del CUF, que son reuniones mensuales en formato ZIP con PDFs adentro
- Los materiales del SUF, que es una reunión trimestral de settlement
- El Integrated Marketplace Protocol, que es el protocolo de referencia

Para navegar SPP.org usamos `requests` y `BeautifulSoup`, que es scraping directo sin necesidad de abrir un navegador. Funciona bien para SPP.org tal como está hoy.

Tenemos también `Playwright` reservado como respaldo para el caso de que SPP.org algún día requiera más interacción de navegador, pero por ahora no es necesario.

Para evitar re-descargar lo mismo, cada archivo queda registrado con su hash SHA-256. Si en la próxima ejecución el archivo no cambió, se salta.

Sobre SharePoint: los archivos sí se guardan localmente en OneDrive. La conexión real a SharePoint mediante la API de Microsoft está pendiente — necesitamos que IT configure los permisos en Azure, pero la lógica ya está escrita y lista para conectarse cuando eso esté disponible.

**Estado: la descarga y deduplicación están funcionando. SharePoint real, pendiente de IT.**

---

## FASE 3 — PROCESAMIENTO Y CROSS-REFERENCE

Esta es la fase más importante, la que le da valor al agente.

El problema es que en el RR Master List puede haber cientos de cambios abiertos. No todos son relevantes — solo los que están próximos a implementarse. ¿Cómo identificamos cuáles? Cruzando dos fuentes.

Primero, leemos el Excel con `openpyxl` y nos quedamos solo con las filas donde el Status es "Open". 

Después extraemos el texto de los PDFs del CUF y el SUF usando `pypdf`, y buscamos con expresiones regulares todos los números de RR mencionados — ya sea como "RR623", "RR-623" o "RR 623". También identificamos las fechas que aparecen cerca de cada mención para saber el timeline.

Un detalle que resolvimos esta semana: el archivo de Action Items del CUF tiene una tabla donde los números de RR aparecen sin el prefijo "RR" — son solo números en la primera columna. Agregamos un extractor específico para ese formato.

El resultado del cross-reference es: los RRs que están Open en el Master List Y además son mencionados en las reuniones CUF o SUF. En la última ejecución identificamos 7 RRs relevantes.

Para cada RR también descargamos su Recommendation Report, que es el documento oficial con todos los detalles del cambio.

Sobre las herramientas: usamos `openpyxl` directamente para el Excel porque la estructura del archivo es estable. En algún momento migraremos a `pandas`, que es más robusto si SPP cambia las columnas de lugar. Para los PDFs usamos `pypdf`, que funciona bien para los documentos actuales. `PyMuPDF` y `pdfplumber` están contemplados para el día que necesitemos extraer tablas complejas.

**Estado: completamente implementado. 7 RRs relevantes identificados en la última ejecución.**

---

## FASE 4 — INTELIGENCIA ARTIFICIAL

La cuarta fase es la que conecta el procesamiento con Claude, el modelo de lenguaje de Anthropic.

La idea es que Claude reciba el texto extraído de los PDFs del CUF y SUF, lo analice, y genere dos cosas: primero un resumen de qué cambios vienen, en qué áreas y con qué timeline. Y segundo, un resumen ejecutivo que destaque los puntos más importantes para el equipo.

Ese resumen es lo que eventualmente va al email y al Slack, en lugar de una lista de números de RR que no le dice nada a nadie.

El archivo `summarizer.py` existe, pero todavía no tiene las llamadas a la API de Claude. Es el próximo paso en el desarrollo.

**Estado: pendiente de implementar. Es el siguiente hito.**

---

## FASE 5 — OUTPUT Y DISTRIBUCIÓN

La quinta fase distribuye los resultados.

Lo que ya funciona: el agente genera un reporte JSON por cada ejecución con todos los RRs relevantes, sus fechas, sus fuentes y los documentos descargados. Ese reporte queda guardado en OneDrive.

También genera un borrador del mensaje de Slack con los 7 RRs, las fechas asociadas y el documento y página donde fue mencionado cada uno. Por ahora ese mensaje se imprime en el log — falta conectarlo al SDK de Slack con el webhook del canal.

Lo que está bloqueado: el email. Necesitamos credenciales del servidor SMTP de PCI, que está en manos de IT. Una alternativa que evaluamos es usar MS Graph Mail, que no requiere servidor SMTP propio y se conecta directo a Outlook, y lo podemos implementar en paralelo con SharePoint.

**Estado: reportes JSON funcionando. Slack listo para conectar. Email bloqueado por IT.**

---

## RESUMEN

Para cerrar: tenemos un agente que hoy mismo corre, se conecta a SPP.org, descarga los 4 documentos relevantes, cruza la información y nos dice exactamente qué 7 cambios regulatorios están próximos a implementarse, con fecha y fuente.

Lo que falta: el resumen en lenguaje natural via Claude, y los canales de distribución reales — Slack, email y SharePoint. Esas tres cosas están en progreso y ninguna requiere cambios en la lógica que ya construimos.

---
