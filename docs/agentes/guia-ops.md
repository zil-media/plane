# Guía para agentes que escriben en Ops

Trabajás con la API pública (`/api/v1/...`, header `X-Api-Key`) como cualquier persona del equipo. Lo que escribís lo lee gente: escribí como un buen compañero, no como un log.

## 1. Reglas de oro

- **Nunca borres contenido ajeno.** Si algo te parece mal, comentalo; no lo saques.
- **Leé → editá lo mínimo → escribí.** Siempre partí de lo último guardado (GET justo antes del PATCH).
- **Cambios chicos y explicados.** Cada edición relevante va acompañada de un comentario que diga qué cambiaste y por qué.
- **Respetá el estilo existente.** Si una página usa H2 + listas, seguí igual. No reformatees lo que no tocás.
- **Sin muros de texto.** Párrafos de 1–3 oraciones, listas para enumerar, títulos para separar.

## 2. HTML que el editor entiende

El editor (TipTap) solo conserva lo que está en su esquema: `packages/editor/src/core/extensions/core-without-props.ts` (work items, comentarios y páginas) y además `DocumentEditorExtensionsWithoutProps` (solo páginas). Todo HTML pasa antes por el sanitizador `apps/api/plane/utils/content_validator.py` (nh3).

| Qué               | Markup                                                                                          | Notas                                                                                                                                                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Párrafo           | `<p>Texto</p>`                                                                                  | Todo texto suelto debería ir en `<p>`.                                                                                                                                                  |
| Títulos           | `<h2>Contexto</h2>`                                                                             | `h1`–`h6`. En páginas el H1 lo da el título: usá H2/H3 en el cuerpo.                                                                                                                    |
| Énfasis           | `<strong>`, `<em>`, `<u>`, `<s>`, `<code>`                                                      | `<code>` es código en línea.                                                                                                                                                            |
| Link              | `<a href="https://...">texto</a>`                                                               | Solo `http`, `https`, `mailto`, `tel` (`SAFE_PROTOCOLS`).                                                                                                                               |
| Listas            | `<ul><li><p>uno</p></li></ul>`, `<ol>…</ol>`                                                    | Se pueden anidar (`<ul>` dentro de `<li>`).                                                                                                                                             |
| Checklist         | `<ul data-type="taskList"><li data-type="taskItem" data-checked="false"><p>Tarea</p></li></ul>` | `data-checked="true"` = hecha.                                                                                                                                                          |
| Cita              | `<blockquote><p>…</p></blockquote>`                                                             |                                                                                                                                                                                         |
| Bloque de código  | `<pre><code>…</code></pre>`                                                                     | Escapá `<`, `>`, `&`. El lenguaje (`class="language-x"`) se puede perder: no dependas de él.                                                                                            |
| Separador         | `<hr>`                                                                                          |                                                                                                                                                                                         |
| Callout           | `<div data-block-type="callout-component"><p>Ojo con…</p></div>`                                | `callout/extension-config.ts`. Opcional `data-background="light-blue"` (gray, peach, pink, orange, green, light-blue, dark-blue, purple — `COLORS_LIST` en `core/constants/common.ts`). |
| Tabla             | `<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>`                     | Primera fila con `<th>` = encabezado.                                                                                                                                                   |
| Mención a persona | ver §3                                                                                          |                                                                                                                                                                                         |
| Imagen            | `<image-component src="<asset_id>" status="uploaded"></image-component>`                        | `custom-image/extension-config.ts`. `src` es el id de un asset subido (ver §6), no una URL.                                                                                             |

**Qué se pierde o rompe** (verificado convirtiendo HTML con el esquema del editor):

- `<div>`, `<span>`, `<mark>`, `<sub>`, `<sup>`, `<details>` y tags desconocidos: se descartan y queda solo el texto.
- `<h7>` y similares → párrafo. `<br>` dentro de un párrafo funciona, pero preferí párrafos separados.
- **Markdown no se interpreta**: `## Título` o `**negrita**` quedan literales. Mandá HTML.
- `<script>`, `on*=`, `javascript:` y atributos fuera de la lista blanca: los borra el sanitizador.
- `<issue-embed-component>` (embeber un work item en una página) no existe en esta edición (`apps/web/ce/components/pages/editor/embed/`) y el sanitizador lo elimina. Para referenciar un work item usá un link a su URL.
- Clases de estilo (`class="editor-paragraph-block"`, etc.) las agrega el editor al guardar. No hace falta mandarlas; si las recibís al leer, podés dejarlas.

## 3. Mencionar a una persona

```html
<p>
  Hola
  <mention-component id="<uuid-nuevo>" entity_identifier="<user_id>" entity_name="user_mention"></mention-component>,
  ¿lo revisás?
</p>
```

- Atributos exactos de `packages/editor/src/core/extensions/mentions/types.ts`: `id`, `entity_identifier`, `entity_name`.
- `entity_identifier` = **id del usuario** (no el email ni el display name). Sacalo de `GET /api/v1/workspaces/<slug>/projects/<project_id>/members/`.
- `entity_name` siempre `user_mention`: es el único que se dibuja (`apps/web/core/components/editor/embeds/mentions/root.tsx`) y el único que dispara notificación (`extract_mentions` en `apps/api/plane/bgtasks/notification_task.py`).
- `id` es un uuid cualquiera, nuevo por mención. La etiqueta va vacía: el editor muestra `@nombre` solo.
- Mencioná solo a quien tiene que actuar. Cada mención notifica.

## 4. Work items

**Crear** — `POST /api/v1/workspaces/<slug>/projects/<project_id>/work-items/`

```json
{
  "name": "Corregir cálculo de IVA en factura B",
  "description_html": "<h3>Contexto</h3><p>…</p><h3>Qué hay que hacer</h3><ul><li><p>…</p></li></ul><h3>Criterio de aceptación</h3><ul data-type=\"taskList\"><li data-type=\"taskItem\" data-checked=\"false\"><p>…</p></li></ul>",
  "state": "<state_id>",
  "priority": "high",
  "labels": ["<label_id>"],
  "assignees": ["<user_id>"],
  "parent": "<work_item_id>"
}
```

- **Título**: corto (≤ 70 caracteres), verbo + objeto, sin prefijos tipo `[BUG]` si ya hay label. Que se entienda en la lista.
- **Descripción**: tres bloques — _Contexto_ (por qué, con datos/links), _Qué hay que hacer_, _Criterio de aceptación_ (checklist verificable). Nada más largo de lo necesario.
- `priority`: `urgent`, `high`, `medium`, `low`, `none`. Estados y labels por id: `GET …/states/`, `GET …/labels/`. No inventes labels nuevos si hay uno que sirve.
- `parent` solo si de verdad es subtarea de otro work item.
- Antes de crear, buscá duplicados: `GET /api/v1/workspaces/<slug>/work-items/search/?search=<texto>`.

**Editar** — `PATCH …/work-items/<id>/`. Mandá solo los campos que cambian. `description_html` reemplaza la descripción entera y en work items gana la última escritura: hacé GET justo antes, cambiá solo tu parte, y escribí enseguida.

**Comentar** — `POST …/work-items/<id>/comments/` con `{"comment_html": "<p>…</p>"}`. Mismo HTML que arriba (incluidas menciones). Un comentario = una idea; si cerrás algo, decí qué hiciste y cómo se verifica.

**Relacionar** — `POST …/work-items/<id>/relations/` con `{"relation_type": "relates_to", "issues": ["<id>"]}` (`blocking`, `blocked_by`, `duplicate`, `relates_to`, `start_before`, `start_after`, `finish_before`, `finish_after`). Links externos: `POST …/work-items/<id>/links/` con `{"url": "https://…", "title": "…"}`.

## 5. Páginas (wiki / docs)

Endpoints (todos por proyecto; no hay páginas a nivel workspace):

- `GET  …/projects/<project_id>/pages/` — lista sin cuerpo. Filtros: `search=`, `parent=root|<page_id>`, `archived=true`.
- `POST …/projects/<project_id>/pages/` — `{"name", "description_html", "access": 0|1, "parent", "kind": "page"|"folder"}`. `access` 0 = pública en el proyecto, 1 = privada (solo vos).
- `GET  …/pages/<page_id>/` — incluye `description_html`.
- `PATCH …/pages/<page_id>/` — `name`, `description_html`, `access` (solo el dueño), `logo_props`.
- `POST|DELETE …/pages/<page_id>/archive/` y `…/lock/` — archivar/restaurar, bloquear/desbloquear.

**Cómo funciona la edición.** La página es un documento colaborativo (Yjs). Tu PATCH se aplica como un _diff_ sobre ese documento a través del servidor `live`: si alguien la tiene abierta, ve tu cambio en vivo y lo que esté tipeando en otros párrafos se conserva. Por eso:

1. `GET` la página justo antes de editar.
2. Tomá su `description_html` y cambiá **solo** el bloque que corresponde (agregar una sección, corregir un dato). No reescribas ni reordenes el resto.
3. `PATCH` con el HTML completo resultante. Lo que no venga en tu HTML se borra del documento: si partís de una copia vieja, pisás lo que otros agregaron después.
4. Dejá constancia: si la página está ligada a un work item, comentá ahí qué cambiaste; si no, avisale al dueño o a quien te lo pidió.

Errores: `PAGE_LOCKED` / `PAGE_ARCHIVED` (400) → no edites, avisá. `503` → el servidor colaborativo no responde; reintentá más tarde, no hubo cambios. Las carpetas (`kind: "folder"`) no tienen cuerpo.

**Estilo en páginas**: el título de la página es el H1; en el cuerpo arrancá con un párrafo que diga para qué sirve la página, después secciones H2. Usá callouts para advertencias, tablas para datos comparables, checklists para procedimientos. Mantené el tono y la estructura que ya tiene la página.

## 6. Imágenes

1. `POST /api/v1/workspaces/<slug>/assets/` con `{"name", "type", "size", "project_id"}` → devuelve `asset_id` y `upload_data` (POST prefirmado a S3).
2. Subí el archivo con `upload_data`.
3. `PATCH /api/v1/workspaces/<slug>/assets/<asset_id>/` con `{"is_uploaded": true}`.
4. Insertá `<image-component src="<asset_id>" status="uploaded"></image-component>`.

Si no podés subir la imagen, poné un link; no uses `<img src="https://…">` salvo que la URL sea pública y estable.

## 7. Checklist antes de escribir

- [ ] ¿Leí el estado actual justo antes?
- [ ] ¿Toco solo lo necesario y respeto el formato existente?
- [ ] ¿El HTML usa solo lo de la tabla de §2?
- [ ] ¿Las menciones tienen `entity_identifier` = user id y `entity_name="user_mention"`?
- [ ] ¿Dejé un comentario explicando el cambio?
