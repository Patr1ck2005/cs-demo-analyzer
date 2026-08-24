// Weapon metadata mirror of cs_analyzer/web/weapons.py (generated once,
// drift-guarded by tests/test_weapons.py::test_js_mirror_matches_python).
// Canvas consumers need synchronous alias/category lookup, so the tables are
// embedded rather than fetched; icon Images are cached asynchronously.
window.WeaponMeta = (function () {
  const ALIASES = {"ak47": "ak47", "ak-47": "ak47", "m4a4": "m4a4", "m4a1": "m4a1", "m4a1_silencer": "m4a1_silencer", "m4a1-s": "m4a1_silencer", "m4a1s": "m4a1_silencer", "galilar": "galilar", "galil ar": "galilar", "galil": "galilar", "famas": "famas", "aug": "aug", "sg553": "sg553", "sg 553": "sg553", "sg556": "sg553", "awp": "awp", "ssg08": "ssg08", "ssg 08": "ssg08", "scar20": "scar20", "scar-20": "scar20", "g3sg1": "g3sg1", "glock": "glock", "glock-18": "glock", "usp": "usp", "usp-s": "usp", "usps": "usp", "usp_silencer": "usp", "p2000": "p2000", "hkp2000": "p2000", "p250": "p250", "fiveseven": "fiveseven", "five-seven": "fiveseven", "tec9": "tec9", "tec-9": "tec9", "cz75a": "cz75a", "cz75-auto": "cz75a", "deagle": "deagle", "desert eagle": "deagle", "elite": "elite", "dual berettas": "elite", "revolver": "revolver", "r8 revolver": "revolver", "mac10": "mac10", "mac-10": "mac10", "mp9": "mp9", "mp7": "mp7", "mp5sd": "mp5sd", "mp5-sd": "mp5sd", "ump45": "ump45", "p90": "p90", "bizon": "bizon", "pp-bizon": "bizon", "nova": "nova", "xm1014": "xm1014", "mag7": "mag7", "mag-7": "mag7", "sawed_off": "sawed_off", "sawed-off": "sawed_off", "sawed off": "sawed_off", "m249": "m249", "negev": "negev", "knife": "knife", "knife_t": "knife", "bayonet": "knife", "butterfly knife": "knife", "flip knife": "knife", "gut knife": "knife", "karambit": "knife", "m9 bayonet": "knife", "skeleton knife": "knife", "stiletto knife": "knife", "bowie knife": "knife", "tactical knife": "knife", "widowmaker knife": "knife", "outdoor knife": "knife", "huntsman knife": "knife", "nomad knife": "knife", "talon knife": "knife", "paracord knife": "knife", "survival knife": "knife", "classic knife": "knife", "falchion knife": "knife", "shadow daggers": "knife", "navaja knife": "knife", "ursus knife": "knife", "kukri knife": "knife", "knife_butterfly": "knife", "knife_flip": "knife", "knife_gut": "knife", "knife_karambit": "knife", "knife_m9_bayonet": "knife", "knife_outdoor": "knife", "knife_skeleton": "knife", "knife_stiletto": "knife", "knife_survival_bowie": "knife", "knife_tactical": "knife", "knife_widowmaker": "knife", "taser": "taser", "zeus x27": "taser", "zeus": "taser", "smokegrenade": "smokegrenade", "smoke grenade": "smokegrenade", "flashbang": "flashbang", "hegrenade": "hegrenade", "high explosive grenade": "hegrenade", "molotov": "molotov", "incgrenade": "incgrenade", "incendiary grenade": "incgrenade", "decoy": "decoy", "decoy grenade": "decoy", "kevlar": "kevlar", "kevlar vest": "kevlar", "kevlarhelmet": "kevlarhelmet", "kevlar & helmet": "kevlarhelmet", "helmet": "kevlarhelmet", "defuser": "defuser", "defuse kit": "defuser", "c4": "c4", "c4 explosive": "c4", "planted_c4": "c4", "inferno": "inferno", "world": "world"};
  const LABELS = {"ak47": "AK-47", "aug": "AUG", "awp": "AWP", "bizon": "PP-野牛", "c4": "C4 炸药", "cz75a": "CZ75 自动手枪", "deagle": "沙漠之鹰", "decoy": "诱饵手雷", "defuser": "拆弹器", "elite": "双持贝瑞塔", "famas": "FAMAS", "fiveseven": "FN57", "flashbang": "闪光弹", "g3sg1": "G3SG1", "galilar": "加利尔 AR", "glock": "格洛克 18 型", "hegrenade": "高爆手雷", "incgrenade": "燃烧弹", "inferno": "火焰", "kevlar": "防弹衣", "kevlarhelmet": "防弹衣+头盔", "knife": "刀", "m249": "M249", "m4a1": "M4A1", "m4a1_silencer": "M4A1 消音版", "m4a4": "M4A4", "mac10": "MAC-10", "mag7": "MAG-7", "molotov": "燃烧瓶", "mp5sd": "MP5-SD", "mp7": "MP7", "mp9": "MP9", "negev": "内格夫", "nova": "新星", "p2000": "P2000", "p250": "P250", "p90": "P90", "revolver": "R8 左轮", "sawed_off": "截短霰弹枪", "scar20": "SCAR-20", "sg553": "SG 553", "smokegrenade": "烟雾弹", "ssg08": "SSG 08", "taser": "泰瑟枪", "tec9": "TEC-9", "ump45": "MP7 冲锋枪 UMP-45", "usp": "USP-S", "world": "环境伤害", "xm1014": "XM1014"};
  const CATEGORIES = {"ak47": "rifle", "m4a4": "rifle", "m4a1": "rifle", "m4a1_silencer": "rifle", "galilar": "rifle", "famas": "rifle", "aug": "rifle", "sg553": "rifle", "awp": "sniper", "ssg08": "sniper", "scar20": "sniper", "g3sg1": "sniper", "glock": "pistol", "usp": "pistol", "p2000": "pistol", "p250": "pistol", "fiveseven": "pistol", "tec9": "pistol", "cz75a": "pistol", "deagle": "pistol", "elite": "pistol", "revolver": "pistol", "mac10": "smg", "mp9": "smg", "mp7": "smg", "mp5sd": "smg", "ump45": "smg", "p90": "smg", "bizon": "smg", "nova": "heavy", "xm1014": "heavy", "mag7": "heavy", "sawed_off": "heavy", "m249": "heavy", "negev": "heavy", "knife": "knife", "kevlar": "gear", "kevlarhelmet": "gear", "defuser": "gear", "taser": "gear", "smokegrenade": "grenade", "flashbang": "grenade", "hegrenade": "grenade", "molotov": "grenade", "incgrenade": "grenade", "decoy": "grenade", "c4": "bomb", "inferno": "world", "world": "world"};
  const HAS_ICON = new Set(["_default", "ak47", "aug", "awp", "bizon", "c4", "cz75a", "deagle", "decoy", "defuser", "elite", "famas", "fiveseven", "flashbang", "g3sg1", "galilar", "glock", "hegrenade", "incgrenade", "inferno", "kevlar", "kevlarhelmet", "knife", "m249", "m4a1", "m4a1_silencer", "m4a4", "mac10", "mag7", "molotov", "mp5sd", "mp7", "mp9", "negev", "nova", "p2000", "p250", "p90", "revolver", "sawed_off", "scar20", "sg553", "smokegrenade", "ssg08", "taser", "tec9", "ump45", "usp", "world", "xm1014"]);
  const ICONS_BASE = "/static/img/weapons/";
  const DEFAULT_ICON = ICONS_BASE + "_default.svg";
  const GUN_CATEGORIES = new Set(["rifle", "sniper", "pistol", "smg", "heavy"]);

  function canonical(name) {
    if (!name) return "_default";
    let n = String(name).trim().toLowerCase().replace(/^weapon_/, "");
    let m;
    while ((m = n.match(/_(txz\d+|vip)$/))) n = n.slice(0, m.index);
    if (ALIASES[n]) return ALIASES[n];
    return ALIASES[n.replace(/-/g, "_").replace(/ /g, "_")] || "_default";
  }

  const imageCache = new Map();
  return {
    canonical,
    label(name) { const c = canonical(name); return LABELS[c] || c; },
    category(name) { return CATEGORIES[canonical(name)] || "unknown"; },
    isGun(name) { return GUN_CATEGORIES.has(category(name)); },
    iconUrl(name) {
      const c = canonical(name);
      if (c === "inferno") return ICONS_BASE + "molotov.svg";
      return HAS_ICON.has(c) ? ICONS_BASE + c + ".svg" : DEFAULT_ICON;
    },
    // Async Image cache for canvas drawImage (LOD weapon badges).
    getIconImage(name) {
      const url = this.iconUrl(name);
      if (imageCache.has(url)) return Promise.resolve(imageCache.get(url));
      return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => { imageCache.set(url, img); resolve(img); };
        img.onerror = () => reject(new Error("icon load failed: " + url));
        img.src = url;
      });
    },
  };
})();
