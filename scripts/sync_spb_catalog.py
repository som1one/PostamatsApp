import json

def main():
    with open("deploy/catalog-sync.bundle.json", "r", encoding="utf-8") as f:
        bundle = json.load(f)

    # 1. Remove previously added extra cells/units
    bundle["cells"] = [c for c in bundle["cells"] if not c["externalCellId"].startswith("seed-spb-nevsky-extra-")]
    
    # Filter inventoryUnits robustly by checking cellExternalCellId
    bundle["inventoryUnits"] = [
        u for u in bundle["inventoryUnits"] 
        if not (u.get("cellExternalCellId") and u["cellExternalCellId"].startswith("seed-spb-nevsky-extra-"))
    ]

    # 2. Duplicate cells from PST_0980 to seed-spb-nevsky
    pst_cells = [c for c in bundle["cells"] if c["lockerExternalLockerId"] == "PST_0980"]
    new_cells = []
    
    cell_mapping = {} # old_cell_id -> new_cell_id
    label_mapping = {} # old_cell_id -> new_label
    
    for c in pst_cells:
        new_c = c.copy()
        new_c["lockerExternalProvider"] = "seed"
        new_c["lockerExternalLockerId"] = "seed-spb-nevsky"
        
        old_id = c["externalCellId"]
        new_id = f"seed-spb-nevsky-extra-{c['label']}"
        new_c["externalCellId"] = new_id
        
        new_label = f"E-{c['label']}"
        new_c["label"] = new_label
        
        new_cells.append(new_c)
        cell_mapping[old_id] = new_id
        label_mapping[old_id] = new_label

    bundle["cells"].extend(new_cells)

    # 3. Duplicate inventory units from PST_0980 to seed-spb-nevsky
    pst_units = [u for u in bundle["inventoryUnits"] if u["lockerExternalLockerId"] == "PST_0980"]
    new_units = []

    for idx, u in enumerate(pst_units):
        new_u = u.copy()
        new_u["lockerExternalProvider"] = "seed"
        new_u["lockerExternalLockerId"] = "seed-spb-nevsky"
        
        old_cell_id = u["cellExternalCellId"]
        if old_cell_id in cell_mapping:
            new_u["cellExternalCellId"] = cell_mapping[old_cell_id]
            new_u["cellLabel"] = label_mapping[old_cell_id]
        
        if new_u.get("serialNumber"):
            new_u["serialNumber"] = f"SEED-SPB-NEVSKY-EXTRA-{idx}-{new_u['serialNumber']}"
        if new_u.get("barcode"):
            new_u["barcode"] = f"seed-spb-nevsky-extra-{idx}-{new_u['barcode']}"
            
        new_units.append(new_u)

    bundle["inventoryUnits"].extend(new_units)
    
    with open("deploy/catalog-sync.bundle.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
