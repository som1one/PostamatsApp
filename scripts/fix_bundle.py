import json

def main():
    with open("deploy/catalog-sync.bundle.json", "r", encoding="utf-8") as f:
        bundle = json.load(f)

    # We want to remove seed-spb-petrogradka and test-moscow-fake-001
    # and map seed-vn-center -> esi/PST_0980
    
    def should_remove_locker(provider, ext_id):
        return (provider == "seed" and ext_id == "seed-spb-petrogradka") or \
               (provider == "esi" and ext_id == "test-moscow-fake-001")

    # 1. Lockers
    new_lockers = []
    for l in bundle.get("lockers", []):
        if should_remove_locker(l["externalProvider"], l["externalLockerId"]):
            continue
        if l["externalProvider"] == "seed" and l["externalLockerId"] == "seed-vn-center":
            l["externalProvider"] = "esi"
            l["externalLockerId"] = "PST_0980"
        new_lockers.append(l)
    bundle["lockers"] = new_lockers

    # 2. Cells
    new_cells = []
    for c in bundle.get("lockerCells", []):
        if should_remove_locker(c["lockerExternalProvider"], c["lockerExternalLockerId"]):
            continue
        if c["lockerExternalProvider"] == "seed" and c["lockerExternalLockerId"] == "seed-vn-center":
            c["lockerExternalProvider"] = "esi"
            c["lockerExternalLockerId"] = "PST_0980"
        new_cells.append(c)
    bundle["lockerCells"] = new_cells

    # 3. Inventory Units
    new_units = []
    for u in bundle.get("inventoryUnits", []):
        if should_remove_locker(u["lockerExternalProvider"], u["lockerExternalLockerId"]):
            continue
        if u["lockerExternalProvider"] == "seed" and u["lockerExternalLockerId"] == "seed-vn-center":
            u["lockerExternalProvider"] = "esi"
            u["lockerExternalLockerId"] = "PST_0980"
        new_units.append(u)
    bundle["inventoryUnits"] = new_units
    
    with open("deploy/catalog-sync.bundle.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
