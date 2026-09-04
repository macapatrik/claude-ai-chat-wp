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

Nahrát `png-to-webp.html` jako `index.html` a vedle něj `og-preview.png`.
Cílová adresa je `https://patrikmaca.cz/nastroje/webp/`.

Při přesunu jinam je potřeba přepsat tři adresy v hlavičce souboru —
`canonical`, `og:url` a `og:image`. Slouží jen pro náhled odkazu při
sdílení a pro vyhledávače; na funkci nástroje nemají vliv.

Stránka nepotřebuje PHP ani databázi a nezasahuje do ničeho, co na
doméně běží. Ve WordPressu i Joomle platí, že přepisovací pravidla
v `.htaccess` posílají na `index.php` jen adresy, kterým na disku
neodpovídá skutečný soubor — statická podsložka se naservíruje přímo.

HTTPS je potřeba kvůli tlačítku „Uložit do složky": File System Access
API prohlížeč mimo zabezpečený kontext nepovolí. Bez HTTPS se tlačítko
skryje a zůstane stahování ZIPu, které funguje všude.

### Omezení

- Metadata (EXIF, ICC profil) se při převodu ztrácejí — canvas je nepřenáší.
  EXIF orientace se ale uplatní, obrázek zůstane správně otočený.
- Kódování WebP vyžaduje Chrome, Edge nebo Firefox. Pokud prohlížeč WebP
  z canvasu neumí, stránka to na začátku pozná a upozorní.
- Bezztrátový režim (kvalita 100) je záležitost Chromia; jinde kvalita 100
  znamená jen „velmi vysoká kvalita" se ztrátovou kompresí.
