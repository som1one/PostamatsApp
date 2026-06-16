import json

def main():
    with open("deploy/catalog-sync.bundle.json", "r", encoding="utf-8") as f:
        bundle = json.load(f)

    def should_remove_locker(provider, ext_id):
        return (provider == "seed" and ext_id == "seed-spb-petrogradka") or \
               (provider == "esi" and ext_id == "test-moscow-fake-001")

    new_cells = []
    for c in bundle.get("cells", []):
        if should_remove_locker(c["lockerExternalProvider"], c["lockerExternalLockerId"]):
            continue
        if c["lockerExternalProvider"] == "seed" and c["lockerExternalLockerId"] == "seed-vn-center":
            c["lockerExternalProvider"] = "esi"
            c["lockerExternalLockerId"] = "PST_0980"
        new_cells.append(c)
    bundle["cells"] = new_cells
    
    with open("deploy/catalog-sync.bundle.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
