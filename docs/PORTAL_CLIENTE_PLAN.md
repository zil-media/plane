# Portal del cliente: calendario de contenidos y carpeta compartida

Plan para que cada cliente de una marca entre a Ops con su propia cuenta y vea **solo** el
calendario de community management de su marca (con los campos que elijamos), comente las
publicaciones y lea las páginas que el equipo deja en la carpeta del cliente.

---

## 1. Qué existe hoy

### En nuestro fork (Marcas)

| Pieza                                  | Dónde                                                                        | Qué hace                                                                                                                      |
| -------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Un proyecto privado por marca y unidad | `db/models/zil_brand.py` (`ZilBrandProject`)                                 | Zil Workspace empuja el roster (`POST /api/zil/sync/brand-projects/`) y Ops crea/renombra/archiva el proyecto.                |
| Equipo por email                       | `utils/zil_brand_projects.py` (`apply_members`, `ZilBrandMember`)            | El roster ya acepta `role: "member"` o `role: "guest"`. Quien nunca entró recibe cuenta y mail (`provision_brand_team_user`). |
| Pestañas del proyecto de marca         | commit `2b5a5b7663`                                                          | Elementos de trabajo, Páginas, Marca.                                                                                         |
| Hoja "Marca"                           | `components/zil-brand/brand-sheet.tsx`, `ZilBrandOps`, `ZilBrandResponsible` | CMs, Responsable por unidad, links de Drive.                                                                                  |
| Carpetas de páginas                    | `Page.FOLDER_KIND`, `Page.parent`                                            | Árbol de páginas con carpetas.                                                                                                |

### En Plane (upstream)

| Pieza                                                      | Estado                                                                                                                                                                                                                                                                 | Sirve para el portal                                                                                                                         |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Diseño calendario** en el web (`issue-layouts/calendar`) | Completo, usa `target_date`/`start_date`                                                                                                                                                                                                                               | Sí, para que el equipo planifique.                                                                                                           |
| **Vistas guardadas** de proyecto                           | Completo                                                                                                                                                                                                                                                               | Sí: una vista "Calendario de contenidos" por marca.                                                                                          |
| **Rol Invitado (guest = 5)**                               | `guest_view_all_features` es todo o nada: en `false` el invitado ve solo lo que él creó; en `true` ve **todo** (todos los items, todas las páginas internas, intake, ciclos, módulos, campos internos) y además puede crear items. Ve la interfaz completa del equipo. | **No**, expone demasiado y no hay forma de limitar campos.                                                                                   |
| **Publicar proyecto** (app `space`, `DeployBoard`)         | Desplegada en prod (`plane-space`). Solo lectura, lista y kanban. Comentarios separados por `access="EXTERNAL"` (ya endurecido). Reacciones/votos opcionales.                                                                                                          | **Sí, es la base**. Le falta: calendario, control de acceso por cliente (hoy cualquiera con el link lee), lista blanca de campos, y páginas. |
| `DeployBoard` tipo `page`                                  | Existe en el modelo, pero la app `space` de la edición comunidad no tiene ruta de páginas                                                                                                                                                                              | Hay que construir la lectura.                                                                                                                |
| Comentario interno vs externo en el web                    | `showAccessSpecifier` en los comentarios                                                                                                                                                                                                                               | Sí: el equipo responde al cliente marcando el comentario como externo.                                                                       |

## 2. Decisión: portal sobre `space`, no invitados en el web

- Invitados en el web obligaría a reescribir permisos en decenas de vistas (items, páginas, ciclos,
  módulos, intake, búsqueda, notificaciones) y el cliente vería la herramienta interna.
- `space` ya es de solo lectura, ya separa comentarios externos, ya está desplegado y ya tiene el
  login de Ops. Le agregamos: **acceso solo para las cuentas del cliente de esa marca**, **calendario**,
  **campos limitados** y **páginas de la carpeta del cliente**.
- El cliente **no es miembro del proyecto ni del workspace**: es un "cliente de la marca". Así nunca
  ve el web del equipo aunque pegue una URL.

## 3. Experiencia del cliente: lo más simple posible

Regla: el cliente no aprende nada. Una sola pantalla, sin menús, sin términos de Ops ("elemento de
trabajo", "estado", "proyecto" no aparecen).

1. **Entrar:** como en el portal de Marketwise. El mail de invitación trae un botón "Ver mi
   calendario" (vence a los 7 días, se puede reenviar); la primera vez elige su contraseña y después
   entra con email y contraseña. La sesión queda abierta; la próxima vez entra directo.
2. **Pantalla única** con dos pestañas: **Calendario** y **Documentos**. Arriba solo el logo de su
   marca. "Mis marcas" aparece únicamente si tiene más de una.
3. **Arriba del calendario:** franja "Para revisar" con las publicaciones que esperan su opinión
   (estado "Aprobación cliente"), cada una como tarjeta grande. Es lo primero que ve.
4. **Calendario:** vista mes en escritorio, lista por día en el celular (mobile primero). Cada
   publicación es una tarjeta con miniatura de la imagen/video, ícono de la red y la fecha. Nada más.
5. **Al abrir una publicación:** se ve como la verá en la red (imagen o video grande, copy debajo),
   la fecha de salida y un estado en palabras simples: "En preparación", "Para revisar",
   "Programada", "Publicada". Debajo, una caja "Escribí tu comentario" y el ida y vuelta con el equipo.
6. **Documentos:** lista plana de los documentos de la carpeta Cliente (título y fecha); al tocar uno
   se lee a pantalla completa.
7. **Avisos al cliente:** un mail cuando hay algo nuevo "Para revisar" o cuando el equipo le responde,
   con botón directo a esa publicación.

## 4. Plan punto a punto

### Paso 1. Cuentas de cliente desde Zil Workspace (hecho en Ops)

1. Zil Workspace (otro repo, `leads`): el estratega, el admin y los demás roles que gestionan la
   marca **invitan al cliente desde la página de la marca**, eligiendo entre los contactos del cliente
   (o cargando uno nuevo), como en Marketwise. Los invitados viajan en el roster de marcas con
   `role: "client"`; revocar = sacarlo de la lista.
2. Ops: modelo `ZilBrandClient(brand_project, email, user nullable)`, por proyecto de marca (como
   `ZilBrandMember`), aplicado como diferencia: agregar, quitar con `membersAuthoritative`, nunca tocar
   si no cambió. Un `client` **no** crea `ProjectMember` ni `WorkspaceMember`. El camino rápido por
   persona (`/sync/user`) ignora `client`.
3. Cuenta: `provision_brand_client_user` crea el usuario sin membresía de workspace; una cuenta
   existente solo se enlaza; una desactivada o un bot quedan sin acceso. **El mail de entrada se manda
   en el paso 4**, al habilitar el portal (antes no hay link al que mandarlo).
4. Si un email es a la vez equipo y cliente, gana el equipo (también en un push parcial).
5. Tests de contrato en `tests/contract/app/test_zil_brand_projects.py` (`TestBrandClients`).
6. **Orden de deploy:** Ops antes que Zil Workspace; un Ops viejo trata `client` como `member`.
7. **Marca suspendida o dada de baja = acceso pausado.** Zil ya manda esa marca como `archived` (o la
   saca del roster) y Ops archiva el proyecto sin tocar a sus clientes; el portal (paso 4) niega el
   acceso mientras el proyecto está archivado. Si la marca vuelve, el acceso vuelve solo. Zil tiene que
   seguir mandando los clientes de una marca archivada, como ya hace con el equipo: una lista
   autoritativa sin ellos los borra (eso es revocar, no pausar).
8. Estado del acceso para la página de la marca en Zil Workspace (invitado / nunca entró / activo,
   último ingreso): Ops lo devuelve por cliente en la respuesta del roster (paso 4, con la invitación).

### Paso 2. Login y redirección del cliente

1. `get_redirection_path`: un usuario sin workspace que es `ZilBrandClient` va al portal en vez de
   onboarding/crear workspace.
2. Su perfil se marca onboarded al aprovisionarlo (no ve el onboarding del equipo).
3. Raíz del portal: "Mis marcas" si tiene más de una; directo al calendario si tiene una.

### Paso 3. Calendario de contenidos para el equipo (web)

1. Al crear o adoptar un proyecto de marca, sembrar (como `seed_studio_defaults`):
   - estados de contenido: Idea, Guion, Diseño, Aprobación cliente, Programado, Publicado;
   - etiquetas de red: Instagram, TikTok, Facebook, LinkedIn, YouTube; de formato: Reel, Post,
     Carrusel, Historia;
   - etiqueta **"Visible al cliente"**;
   - vista guardada **"Calendario de contenidos"** con diseño calendario y filtro de contenido.
2. Fecha de publicación = `target_date` (lo que el calendario ya usa).
3. Backfill con un comando para las marcas existentes (idempotente).

### Paso 4. Portal: acceso y datos (API `space`)

1. Nuevo modelo `ZilClientPortal(project 1:1, deploy_board, pages_folder → Page, enabled)`.
   Al habilitarlo se crea el `DeployBoard` del proyecto con comentarios activos, actividad apagada,
   reacciones y votos apagados, intake apagado.
2. Guardia común para **todas** las vistas de `plane/space/views` (proyecto, items, detalle,
   comentarios, reacciones, assets, labels, estados): si el board tiene portal, exige login y que el
   usuario sea `ZilBrandClient` de esa marca o miembro del proyecto. Si no, 404 (no revela que existe).
   Un cliente de una marca archivada (suspendida o dada de baja) no entra: ve "Acceso en pausa".
3. Solo items con la etiqueta "Visible al cliente" (filtro en el queryset, también en detalle y
   comentarios).
4. Serializer de portal con lista blanca: nombre, descripción, estado, fecha de publicación, etiquetas,
   adjuntos (imágenes/video) y links. Fuera: responsables, prioridad, estimaciones, ciclos, módulos,
   sub-items, relaciones, actividad, comentarios internos.
5. Tests de contrato: cliente de otra marca → 404; anónimo → 404; item sin etiqueta → 404; comentario
   interno nunca aparece; campos ocultos no salen en la respuesta.
6. Invitación como en Marketwise: mail con link de un solo uso que vence a los 7 días, donde el cliente
   elige su contraseña; reenviar invalida el anterior. Se manda al habilitar el portal y a cada cliente
   que se sume después; `invited_at` y el token hasheado en `ZilBrandClient`.

### Paso 5. Portal: calendario (front `apps/space`)

1. Construir la pantalla de la sección 3: franja "Para revisar", calendario mes (escritorio) y lista
   por día (celular), tarjetas con miniatura, detalle tipo publicación con comentarios (el componente
   de comentarios de `space` ya existe). Estados traducidos a las cuatro palabras simples.
2. Sacar de `space` para el portal: barra de filtros, selector de diseño, votos, reacciones e intake.
3. Marca Zil Ops según `docs/ZIL_OPS_REBRAND.md`, modo claro, logo y color de la marca del cliente.

### Paso 6. Comentarios del cliente

1. El cliente comenta en el portal (queda `EXTERNAL`).
2. En el web el equipo lo ve con su marca de externo; responde marcando el comentario como externo.
3. Aviso a los CMs y al Responsable de la unidad cuando comenta un cliente (notificación in-app y
   mail), usando `ZilBrandOps.community_managers` y `ZilBrandResponsible`.
4. Mail al cliente cuando una publicación pasa a "Aprobación cliente" o el equipo le responde con un
   comentario externo, con link directo a la publicación.

### Paso 7. Carpeta del cliente en Páginas

1. Sembrar en cada proyecto de marca una carpeta **"Cliente"** (`FOLDER_KIND`) y apuntarla en
   `ZilClientPortal.pages_folder`. Compartir = mover la página adentro; dejar de compartir = sacarla.
2. API `space`: árbol de la carpeta y lectura de una página (`description_html`), con la misma
   guardia del paso 4; imágenes de la página por el endpoint de assets del portal.
3. Confirmar que `apps/live` deja `description_html` al día al guardar; si no, generarlo al leer.
4. Front `space`: pestaña "Documentos" con el árbol y lector de solo lectura de `@plane/editor`.

### Paso 8. Control del equipo en la hoja "Marca"

1. Sección "Portal del cliente" en `brand-sheet.tsx`: activar/desactivar, copiar link, lista de
   cuentas de cliente (de solo lectura, vienen de Zil Workspace).
2. En el item: acción rápida "Mostrar al cliente" (pone/quita la etiqueta). En la página: indicador
   cuando está dentro de la carpeta Cliente.

### Paso 9. Verificación y salida

1. Tests de contrato del backend (pasos 1, 2, 4, 6, 7) y unitarios del front tocado.
2. Pasada real: una marca piloto, una cuenta de cliente de prueba, ver calendario, comentar, leer
   página, y comprobar que con otra cuenta no entra.
3. Deploy (necesita OK): primero Ops, después Zil Workspace con `role: "client"`.

## 5. Lo que hay que decidir antes de construir

1. ¿El cliente ve todos los items del calendario o solo los marcados "Visible al cliente"? (el plan
   asume marcados).
2. ¿El cliente puede aprobar (mover a "Programado") o solo comentar? (el plan asume solo comentar).
3. ¿Comentarios también en las páginas de la carpeta Cliente, o solo lectura? (el plan asume lectura).
