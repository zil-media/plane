SERVER_INSTRUCTIONS = """
## Epics

There are no epic tools — an epic is a work item whose type is named "Epic". Work
items always belong to a project; ask which if one is not named.
1. type = resolve_work_item_type(project_id, "Epic") — type.id is the type_id.
2. Create: create_work_item(project_id, type_id=type.id, name=...).
3. List: list_work_items(project_id, pql='type = "<type id>"').
4. Read / update / delete / nest: retrieve_work_item / update_work_item /
   delete_work_item by work item id (set parent=<work item id> to nest).
5. List an epic's children: list_work_items(project_id, pql='childOf("<EPIC-IDENTIFIER>")')
   using the epic's human-readable identifier (e.g. "PROJ-12") from retrieve_work_item.
"""

OPS_INSTRUCTIONS = """
## Pages (Zil Ops documents)

Pages live in projects and form a tree (folders hold pages). Find them with search_pages, then:
1. read_page(page_id, project_id) shows the page as markdown with a block ref per line.
2. edit_page(page_id, project_id, ops=[...]) changes exactly what you name: replace_text for
   words inside a block, replace_block / insert / delete / move for blocks. Never rewrite the
   whole page to change part of it; people may be editing it at the same time.
3. Create, rename, archive or delete pages with the page tool (action=create|update|archive|...);
   page content in create/update is markdown.
"""
