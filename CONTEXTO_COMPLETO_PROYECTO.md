# SPP Market Intelligence Agent — Contexto Completo del Proyecto

## 📋 RESUMEN EJECUTIVO

Estamos construyendo un **agente de software automatizado** que monitorea cambios regulatorios del mercado SPP/SSPIM (energy trading). El agente descarga documentos, identifica cambios relevantes usando IA (Claude), y notifica a stakeholders automáticamente.

**Objetivo:** Eliminar el trabajo manual de revisar documentos de SPP.org cada mes y generar reportes.

---

## 🏗️ ARQUITECTURA DEL PROYECTO

### Fase 1: GATHERING (Recopilación de Información) ← AQUÍ ESTAMOS

**Entrada:** Documentos de SPP.org
**Salida:** Resumen ejecutivo con RRs (Revision Requests) relevantes

**Pipeline (5 etapas):**

1. **TRIGGER** → Windows Task Scheduler ejecuta `run_agent.bat` (ejecución mensual/trimestral)
2. **WEB SCRAPING** → Descarga 4 documentos de SPP.org en paralelo:
   - RR Master List (Excel)
   - CUF Meeting Materials (ZIP → PDFs)
   - SUF Meeting Materials (PDF)
   - Integrated Marketplace Protocol (ZIP)
3. **DATA PROCESSING** → Procesa datos:
   - Parsea Excel: filtra RRs con Status='Open'
   - Extrae texto de PDFs
   - **Cross-reference:** cruza RRs mencionados en CUF/SUF ∩ RRs abiertos = lista de relevantes
4. **AI/LLM** → Claude API genera:
   - Resumen de contenido: cambios, área, timeline
   - Resumen ejecutivo: highlights de lo más importante
5. **OUTPUT** → Distribuye:
   - Email a PCI Organization
   - Email a Stakeholders
   - Slack notification
   - SharePoint (histórico)

### Fase 2: ANÁLISIS (Settlement Protocol Comparison)
Comparar versiones del protocolo v118 vs v117, detectar cambios no documentados.

### Fase 3: CREACIÓN DE STORIES (Jira Integration)
Generar Jira stories automáticamente basadas en cambios detectados.

---

## 💾 ESTADO ACTUAL DEL CÓDIGO

Tu compañera ha implementado **los pasos 1-3 del pipeline** (Trigger → Scraping → Processing).
Lo que **FALTA implementar** es:
- ❌ **Claude API Summarizer** (`summarizer.py` está vacío)
- ❌ **Email real** (SMTP/MS Graph Mail) — blocker de IT
- ⚠️ **Slack real** (solo draft en logs)
- ⚠️ **SharePoint real** (ahora es LocalSharePointClient, mock local)

---

## 🎯 PRÓXIMO HITO: Implementar Claude Integration

**Qué vamos a hacer:**
1. Tomar el texto extraído de los PDFs del CUF/SUF
2. Enviarle a Claude API con un prompt estructurado
3. Recibir un JSON con resumen ejecutivo
4. Guardarlo y prepararlo para email/Slack

**Inputs a Claude:**
- Texto bruto extraído del CUF/SUF PDF
- Lista de RRs relevantes (IDs + metadatos)
- Contexto: qué cambios vienen, cuándo, qué documentos impactan

**Outputs esperados de Claude:**
```json
{
  "summary": "Resumen en 2-3 párrafos de qué cambia",
  "key_rrs": [
    {
      "rr_number": "782",
      "title": "RTO Expansion...",
      "impact": "High",
      "timeline": "Fall 2026",
      "description": "Cambios en market rules..."
    }
  ],
  "dates": ["Fall 2026", "Q4 2026"],
  "highlights": [
    "Cambio crítico en cálculos de settlement",
    "Nuevas reglas para participación de generadores"
  ]
}
```

---

## 🔧 STACK TECNOLÓGICO

### Core
- **Python 3.11+** — lenguaje principal
- **Flask** — dashboard local (opcional)
- **Windows Task Scheduler** — trigger (no en código, es config del SO)

### Web Scraping & Downloads
- **requests** — descargas HTTP
- **BeautifulSoup4** — parse HTML de SPP.org
- **Playwright** — browser automation (reservado para flujos complejos)

### Data Processing
- **pandas** 🔄 ← **USAREMOS AHORA** (mejora del código actual)
- **openpyxl** — lectura de Excel
- **pypdf** — extracción de texto de PDFs
- **PyMuPDF/pdfplumber** — alternativas más robustas para PDFs con tablas

### AI/LLM
- **Anthropic Claude API** — modelo `claude-sonnet-4-20250514`
- Características: structured output, visión (si necesitamos procesar imágenes de documentos)

### Cloud & Storage
- **MS Graph API** — acceso a SharePoint (cuando esté listo)
- **azure-identity** / **azure-storage** — autenticación y almacenamiento

### Notificaciones
- **SMTP (PCI server)** — envío de emails (blocker actual: no tenemos credenciales)
- **MS Graph Mail API** — alternativa para emails vía Outlook
- **slack-sdk** — envío a Slack

### Config & Security
- **PyYAML** — archivos de configuración
- **python-dotenv** — variables de entorno
- **keyring** — almacenamiento seguro de credenciales

### Testing & Logging
- **pytest** — tests unitarios
- **logging** — logging estructurado con timestamps

---

## 📁 ESTRUCTURA DEL PROYECTO (ACTUAL)

```
spp-rr-automation/
├── main.py                              # Orquestador principal
├── config.py                            # Configuración (no incluido en upload)
├── requirements.txt                     # Dependencias Python
├── run_agent.bat                        # Script que lanza main.py (Windows)
│
├── src/
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── spp_client.py               # Cliente para scraping de SPP.org
│   │   └── download_utils.py           # Utilidades: sanitize, hash, download
│   │
│   ├── documents/
│   │   ├── __init__.py
│   │   ├── excel_parser.py             # Lee RR Master List (openpyxl)
│   │   ├── pdf_parser.py               # Extrae texto de PDFs (pypdf)
│   │   ├── rr_extractor.py             # Regex para menciones de RRs
│   │   └── zip_utils.py                # Extrae archivos de ZIPs (seguro)
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── notifier.py                 # Draft de Slack (aún no envía)
│   │
│   ├── sharepoint/
│   │   ├── __init__.py
│   │   └── sharepoint_client.py        # LocalSharePointClient (mock)
│   │
│   ├── state/
│   │   ├── __init__.py
│   │   └── metadata_store.py           # Estado: hashes, documento descargados
│   │
│   └── summaries/
│       ├── __init__.py
│       └── summarizer.py               # ❌ VACÍO — aquí va Claude integration
│
├── logs/
│   └── run-YYYYMMDD-HHMMSS.log        # Logs por ejecución
│
├── downloads/                           # Descargas temporales
│   ├── rr_master_list/
│   ├── cuf/
│   ├── suf/
│   ├── protocol/
│   └── recommendation_reports/
│
├── extracted/                           # Archivos extraídos de ZIPs
│   ├── cuf/
│   ├── suf/
│   └── recommendation_reports/
│
├── reports/                             # Reportes JSON por ejecución
│   ├── run-YYYYMMDD-HHMMSS.json
│   └── relevant-rrs-YYYYMMDD-HHMMSS.json
│
└── sharepoint_mirror/                   # Mock local de SharePoint (testing)
```

---

## 🔑 CONCEPTOS CLAVE

### RR (Revision Request)
Un cambio propuesto en el protocolo/reglas del mercado SPP. Tiene:
- Número único (ej: RR782, RR623)
- Status: Open, Approved, Rejected, etc.
- Título y descripción
- Documentos impactados: market rules, cálculos, GUI, extracts
- Primary Working Group que lo propone
- Fechas de release (Fall 2026, etc.)

### CUF (Congestion Users Forum)
Reuniones **mensuales** donde se discuten cambios próximos. Los documentos publicados contienen:
- Agenda y materiales de reunión
- Mentions de RRs que vienen
- Próximas releases

### SUF (Settlement Users Forum)
Reuniones **trimestrales** sobre settlement. Documentos contienen:
- Release notes (ej: "Fall 2026 Release")
- RRs que afectarán el settlement
- Impacto en cálculos y procesos

### Cross-Reference
El paso crítico donde cruzamos:
- RRs mencionados en CUF/SUF PDFs
- Con RRs que están "Open" en el Master List
- La **intersección** = RRs relevantes para monitorear

---

## 📊 FLUJO DE EJECUCIÓN (CON DETALLE)

```
1. Windows Task Scheduler lanza run_agent.bat
   ↓
2. run_agent.bat ejecuta: python main.py run [--dry-run]
   ↓
3. main.py orquesta:
   ├─ Carga config (config.py)
   ├─ Inicializa logging (logs_dir/)
   ├─ Carga state anterior (metadata_store.json) para evitar re-procesar
   │
   ├─ Crea SppClient (scraper a SPP.org)
   │
   ├─ Busca 4 documentos en SPP.org:
   │   ├─ RR Master List (latest .xlsx)
   │   ├─ CUF Meeting Materials (latest .zip)
   │   ├─ SUF Meeting Materials (latest .pdf)
   │   └─ Integrated Marketplace Protocol (latest .zip, optional)
   │
   ├─ Para cada documento:
   │   ├─ Verifica si ya lo descargó (por ID + nombre + hash)
   │   ├─ Si no lo tiene, descarga
   │   └─ Guarda metadata (ID, URL, hash SHA256, local_path)
   │
   ├─ Parsea RR Master List:
   │   ├─ Lee Excel con openpyxl
   │   └─ Filtra solo Status='Open' → dict de RRRecord
   │
   ├─ Procesa CUF (si es nuevo):
   │   ├─ Extrae PDFs del ZIP
   │   ├─ Para cada PDF:
   │   │   ├─ Extrae texto con pypdf
   │   │   ├─ Busca menciones de RRs con regex (RRN, RR-N, RR N)
   │   │   ├─ Extrae fechas asociadas
   │   │   └─ Sube PDF a SharePoint
   │   └─ Guarda metadata de mentions
   │
   ├─ Procesa SUF (si es nuevo):
   │   └─ Igual que CUF, pero es un solo PDF
   │
   ├─ Cross-reference:
   │   ├─ Cruza: RRs_mencionados ∩ RRs_Open = RRs_relevantes
   │   └─ Para cada RR relevante, descarga su Recommendation Report
   │
   ├─ ⭐ CLAUDIFICATION (AQUÍ ENTRA TU TRABAJO):
   │   ├─ Claude Summarizer: extrae cambios de CUF/SUF
   │   └─ Claude Executive Summary: consolida todo con highlights
   │
   ├─ Almacena en SharePoint:
   │   ├─ Documentos descargados
   │   ├─ Recommendation Reports
   │   └─ Resumen ejecutivo (JSON)
   │
   ├─ Envía notificaciones:
   │   ├─ Email a PCI Organization
   │   ├─ Email a Stakeholders
   │   └─ Slack al canal de market updates
   │
   ├─ Guarda reportes:
   │   ├─ run-ID.json (resumen completo de la ejecución)
   │   └─ relevant-rrs-ID.json (solo los RRs relevantes)
   │
   └─ Actualiza state (metadata_store.json) para próxima ejecución
```

---

## ⚡ PUNTO CRÍTICO: CROSS-REFERENCE

Este es el corazón del agente y lo que lo diferencia de un simple downloader.

**Ejemplo:**
```
RR Master List tiene: RR782, RR623, RR728 (Status='Open')
CUF PDF menciona: "RR782 será implementado en Fall 2026, RR623..."
SUF PDF menciona: "Fall 2026 Release incluye RR623, RR728"

Resultado: RRs relevantes = {782, 623, 728}
(los que están OPEN y además son mencionados en reuniones)
```

Esto te permite filtrar ruido: hay cientos de RRs abiertos, pero solo unos pocos son próximos a implementarse.

---

## 🎬 PRÓXIMOS PASOS (ORDEN RECOMENDADO)

### 1. Mejorar excel_parser.py (FÁCIL)
Cambiar openpyxl puro a pandas + openpyxl:
- Más legible
- Más resiliente a cambios en estructura Excel
- Preparación para Fase 2

### 2. Implementar summarizer.py (CRÍTICO)
Crear dos funciones que usen Claude API:
```python
def claude_summarize_pdf(text: str) -> dict:
    # Input: texto extraído de CUF/SUF PDF
    # Output: JSON con cambios, RRs, fechas

def claude_executive_summary(pdf_summary: dict, relevant_rrs: list) -> dict:
    # Input: resumen de PDF + contexto de RRs relevantes
    # Output: JSON con resumen ejecutivo + highlights
```

### 3. Implementar notifier real (IMPORTANTE)
Actualmente solo loguea el draft. Implementar:
- Slack SDK para enviar mensajes reales
- Email vía SMTP (cuando IT dé credenciales)

### 4. Mejorar sharepoint_client (CUANDO ESTÉ LISTO)
Reemplazar LocalSharePointClient con MS Graph API real.

---

## 🔐 CONFIGURACIÓN REQUERIDA

Tu compañera probablemente tiene un `config.py` similar a esto:

```python
# config.py
import os
from pathlib import Path

SPP_BASE_URL = "https://spp.org"
DOCUMENT_SEARCH_PATH = "/Documents/Search"
RR_MASTER_QUERY = "RR Master List"
CUF_QUERY = "CUF Meeting Materials"
SUF_QUERY = "SUF Meeting Materials"
PROTOCOL_QUERY = "Integrated Marketplace Protocols"

LOW_TEXT_CHAR_THRESHOLD = 200  # Advertir si PDF tiene muy poco texto

RUNTIME_DIR = Path.home() / ".spp_rr_automation"
SHAREPOINT_FOLDERS = {
    "rr_master_list": "RR Master List",
    "cuf": "CUF Materials",
    "suf": "SUF Materials",
    "protocol": "Protocols",
    "recommendation_reports": "RR Reports",
}

def ensure_runtime_dirs(config):
    config.downloads_dir.mkdir(parents=True, exist_ok=True)
    config.extracted_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    config.state_file.parent.mkdir(parents=True, exist_ok=True)
```

**Variables de entorno necesarias (.env):**
```
ANTHROPIC_API_KEY=sk-ant-... (para Claude)
SHAREPOINT_SITE=https://pcicompany.sharepoint.com/sites/energy
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... (si usas webhooks)
SMTP_SERVER=smtp.pci.local (cuando IT lo habilite)
SMTP_USER=agent@pci.local
SMTP_PASSWORD=... (guardar en keyring, no en .env)
```

---

## 📝 TAREAS INMEDIATAS PARA CLAUDE EN VS CODE

Cuando abras el proyecto en VS Code con este contexto, Claude podrá ayudarte a:

1. **Revisar y mejorar `excel_parser.py`** con pandas
2. **Implementar `summarizer.py`** con Anthropic SDK
3. **Crear prompts estructurados** para Claude que generen JSON válido
4. **Mejorar `notifier.py`** para enviar Slack reales
5. **Escribir tests** unitarios para cada módulo
6. **Documentar la API** de cada función
7. **Debuggear issues** en el scraping de SPP.org
8. **Optimizar el cross-reference** logic

---

## 🚀 COMANDOS ÚTILES PARA EJECUTAR

```bash
# Setup inicial
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Ejecutar en dry-run (sin descargar ni almacenar)
python main.py run --dry-run

# Ejecutar en serio
python main.py run

# Ver logs
type logs\run-YYYYMMDD-HHMMSS.log

# Revisar reportes
type reports\relevant-rrs-YYYYMMDD-HHMMSS.json
```

---

## 📚 REFERENCIAS

- **Diagrama de flujo Phase 1:** `fase1_architecture_drawio.xml` (importar en draw.io)
- **Diagrama HTML interactivo:** `architecture_diagram.html`
- **Resumen ejecutivo:** `resumen_fase1_para_presentacion.md`
- **Transcripción de Miquel:** Usa Flask + PyYAML + keyring (mismo stack que nosotros)
- **Repositorio actual:** Código de tu compañera en los uploads

---

## ❓ PREGUNTAS FRECUENTES

**P: ¿Por qué cross-reference es importante?**
R: Hay ~1000 RRs abiertos a nivel nacional. Solo ~10-50 son próximos a implementarse en una release. Sin cross-reference, el resumen sería inútil.

**P: ¿Por qué no bajar TODO de SPP.org?**
R: Sería 100GB+ de datos. El cross-reference filtra solo lo relevante.

**P: ¿Claude siempre va a entender los PDFs?**
R: El texto extraído con pypdf a veces tiene OCR errors o formatos raros. Claude es robusto ante eso, pero a veces necesitaremos PyMuPDF o visión de Claude para PDFs complejos.

**P: ¿Y si SPP.org cambia la estructura HTML?**
R: El scraper fallará. Solución: usar Playwright para emular un navegador real (más robusto pero más lento). Ya está reservado en el código.

**P: ¿Cuándo entra Fase 2?**
R: Cuando Phase 1 esté en producción y ejecutándose limpiamente cada mes.

---

## 🎯 OBJETIVO FINAL

Un **agente autónomo** que:
1. Se ejecuta sin intervención humana (Windows Task Scheduler)
2. Descarga documentos de SPP.org automáticamente
3. Identifica qué cambios vienen y cuándo (cross-reference)
4. Usa IA para generar un resumen claro y accionable
5. Notifica a stakeholders por email y Slack
6. Mantiene historial en SharePoint para auditoría

**Resultado:** El equipo de PCI está **siempre informado** sobre cambios regulatorios sin tener que revisar SPP.org manualmente.

---

Cualquier pregunta sobre el contexto o el código, pídele a Claude en VS Code que te lo explique. Él tendrá todo este contexto disponible.
