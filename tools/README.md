# Nástroje

## `png-to-webp.html` — dávkový převodník PNG → WebP

Jeden samostatný HTML soubor bez závislostí. Stáhni ho a otevři dvojklikem
v prohlížeči, nebo ho nahraj kamkoliv na web — funguje i z `file://`.

Konverze běží celá v prohlížeči přes Canvas API. Žádný obrázek se nikam
neodesílá a nástroj nepotřebuje připojení k internetu.

### Co umí

- Přetažení jednotlivých souborů i celých složek (rekurzivně), nebo výběr přes dialog
- Vstupy: PNG, JPG, GIF, BMP, AVIF, TIFF — cokoliv, co prohlížeč umí dekódovat
- Nastavitelná kvalita (75–85 je pro fotky ideální; 100 = bezztrátový režim)
- Volitelné zmenšení delší strany na zadaný počet pixelů
- Souběžné zpracování více souborů najednou (výchozí podle počtu jader)
- Volba „ponechat originál, pokud by WebP byl větší" — u malých obrázků
  s průhledností se to stává
- Zachování struktury podsložek
- Výstup: ZIP se všemi soubory, uložení přímo do složky na disku
  (Chrome/Edge přes File System Access API), nebo stažení po jednom
- Průběžná statistika: původní velikost, výsledná velikost, úspora, chyby

### Ověřeno

Testováno headless Chromiem na 500 fotkách (1,4 GB PNG):
převod za ~50 s, výstup 172 MB, úspora 88 %, bez chyb.
Vygenerovaný ZIP prošel kontrolou `unzip -t` i Python `zipfile`.
ZIP writer je vlastní (žádná externí knihovna) a zvládá i Zip64 —
ověřeno na archivu se 70 000 položkami.

### Nasazení

Živá adresa je `https://macapatrik.github.io/claude-ai-chat-wp/`, servírovaná
GitHub Pages ze složky `docs/` na této větvi. Ta složka je nasazovaný web:

- `docs/index.html` — kopie `tools/png-to-webp.html`
- `docs/og-preview.png` — náhled odkazu při sdílení
- `docs/.nojekyll` — vypne zpracování Jekyllem, servíruje se to tak, jak to leží

Po úpravě `tools/png-to-webp.html` je potřeba kopii obnovit
(`cp tools/png-to-webp.html docs/index.html`) a pushnout. Pages se překlopí samy.

Hostování na GitHub Pages je záměr. Dřív nástroj běžel v podsložce webu na
sdíleném hostingu a nasazení nové verze toho webu přes FTP celou složku
smazalo. Pages leží mimo, takže se to nemůže opakovat.

Při přesunu jinam je potřeba přepsat tři adresy v hlavičce HTML —
`canonical`, `og:url` a `og:image`. Slouží jen pro náhled odkazu při
sdílení a pro vyhledávače; na funkci nástroje nemají vliv.

Pro nasazení na běžný hosting přes FTP zůstává v `tools/deploy/`
připravený balíček i `.htaccess`, který vypne přepisovací pravidla
zděděná z kořene webu.

### Omezení

- Metadata (EXIF, ICC profil) se při převodu ztrácejí — canvas je nepřenáší.
  EXIF orientace se ale uplatní, obrázek zůstane správně otočený.
- Kódování WebP vyžaduje Chrome, Edge nebo Firefox. Pokud prohlížeč WebP
  z canvasu neumí, stránka to na začátku pozná a upozorní.
- Bezztrátový režim (kvalita 100) je záležitost Chromia; jinde kvalita 100
  znamená jen „velmi vysoká kvalita" se ztrátovou kompresí.
