# Eventlook Sale Notifications

WordPress plugin that turns an Eventlook sale webhook into an instant push notification on your team's phones (ntfy and/or Pushover). Runs on your existing WordPress site — no extra server.

*Dokumentace níže je česky.*

---

## Co to dělá

Eventlook (nebo jakýkoli relay, třeba Make/Zapier) pošle POST na endpoint na vašem webu, plugin z payloadu vytáhne akci, počet vstupenek, částku a kupujícího a okamžitě to pošle jako push do mobilu:

```
🎟️ Prodáno 2× Kapela X — Lucerna
690 CZK · Jan Novák
Dnes celkem: 7 ks / 4 830 CZK
```

Součástí je denní počítadlo (kolik vstupenek a za kolik se dnes prodalo), ochrana proti duplicitám (stejné číslo objednávky se do 24 h nepošle dvakrát) a log posledních 25 requestů včetně syrového payloadu — podle něj se doladí mapování polí.

## Instalace

1. Nahrajte složku `eventlook-notifier/` do `wp-content/plugins/` (nebo ji zazipujte a nahrajte přes **Pluginy → Přidat nový → Nahrát plugin**).
2. Aktivujte plugin.
3. Otevřete **Nastavení → Eventlook Notifications**.

## Nastavení krok za krokem

### 1. Kam mají chodit oznámení

**ntfy** (zdarma, doporučeno):
1. Nainstalujte si appku ntfy ([iOS](https://apps.apple.com/app/ntfy/id1625396347), [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) — každý z týmu.
2. Vymyslete si **náhodný název tématu**, např. `vstupenky-7f3a91c2`. Na veřejném serveru ntfy.sh si téma může přečíst kdokoli, kdo název uhodne, takže ať je dlouhý a nezapamatovatelný — nebo si u ntfy.sh založte účet, téma si zarezervujte jako soukromé a vyplňte v nastavení **Access token**.
3. V appce dejte *Subscribe to topic* a zadejte stejný název.
4. V nastavení pluginu zaškrtněte **Enabled**, vyplňte téma a uložte.

**Pushover** (jednorázově placená appka): v nastavení vyplňte *Application token* (vytvoříte na pushover.net → Create Application) a *User/Group key*. Pro celý tým se hodí group key.

Klidně zapněte obojí — pošle se do obou.

### 1b. Vlastní znělka / cinknutí

**Pushover — vlastní MP3, stejné pro celý tým.** Na pushover.net (na účtu, který vlastní aplikaci) je sekce **Sounds → Upload Sound**: nahrajete MP3, max **500 kB**, pro iOS **max 30 sekund**, jinak se nepřehraje. Pak v nastavení pluginu klikněte na **Load sounds from Pushover** — načte se seznam vestavěných i vašich nahraných zvuků a vybraný se uloží do pole *Sound*. Zvuk se přehraje **všem**, komu notifikace přijde, protože se posílá spolu se zprávou. Funguje na iOS 14+, Androidu i desktopu.

Z vestavěných se na prodej vstupenky hodí `cashregister`, `magic`, `cosmic` nebo `incoming`.

**ntfy — zvuk si nastavuje každý telefon sám.** Sender zvuk neurčuje, takže vlastní znělka se nastavuje v appce na každém mobilu zvlášť:

- *Android*: appka má nastavení per odběr (subscription) a zároveň jeden **notification channel na každou prioritu**. Dlouhý stisk ikony appky → **Notifications** → příslušný kanál → vlastní zvuk (soubor stačí nakopírovat do složky `Notifications` v telefonu). Dá se tam zapnout i to, aby notifikace zvonila, dokud ji někdo neodklikne.
- *iOS*: appka vlastní zvuky nepodporuje, zazní systémové cinknutí.

Protože každá priorita má vlastní kanál, jde toho využít: běžný prodej posílat s prioritou 4 a nastavit mu decentní tón, a kdyby se posílalo něco výjimečného s prioritou 5 (max), zazní na Androidu jiný zvuk.

**Nejjistější varianta pro pokladnu/kancelář** je prohlížeč — stránka otevřená na počítači u pokladny, která si sama přehraje libovolné MP3 nahlas přes reproduktory. To plugin zatím neumí, ale je to malé doplnění; řekněte, jestli to chcete.

### 2. Vygenerujte secret a předejte URL Eventlooku

Na stránce nastavení najdete:

- **Webhook URL** — `https://vas-web.cz/wp-json/eventlook/v1/sale`
- **URL s tokenem** — stejná URL s `?token=…`, když protistrana umí jen vložit odkaz bez hlaviček

Eventlooku (jejich podpoře) stačí napsat: *pošlete nám POST s JSON tělem na tuhle URL při každém zaplaceném prodeji*. Secret jde poslat kterýmkoli z těchto způsobů — plugin akceptuje všechny:

| Způsob | Co poslat |
|---|---|
| Hlavička | `X-Eventlook-Token: <secret>` (funguje i `X-Webhook-Token`, `X-Auth-Token`, `X-Api-Key`) |
| Hlavička | `Authorization: Bearer <secret>` |
| Query | `?token=<secret>` |
| Podpis | `X-Eventlook-Signature: sha256=<HMAC-SHA256 těla se secretem>` (i `X-Hub-Signature-256`) |

Bez platného tokenu endpoint vrací 401, takže URL může klidně být veřejná.

Ověření spojení bez odeslání notifikace: `GET /wp-json/eventlook/v1/ping` se stejným tokenem.

### 3. Otestujte

Tlačítko **Send test notification** v administraci pošle vzorovou zprávu do všech zapnutých kanálů a výsledek (včetně případné chyby z ntfy/Pushoveru) zobrazí hned pod ním.

Test celého webhooku z příkazové řádky:

```bash
curl -X POST "https://vas-web.cz/wp-json/eventlook/v1/sale?token=SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"event_name":"Kapela X — Lucerna","quantity":2,"total":690,"currency":"CZK","buyer_name":"Jan Novák","order_id":"A-9931"}'
```

### 4. Dolaďte mapování polí (většinou netřeba)

Eventlook nemá veřejnou dokumentaci k formátu webhooku, takže plugin hledá pole podle běžných názvů — `event_name`, `nazev_akce`, `title`, `quantity`, `pocet_vstupenek`, `total_price`, `celkem`, `buyer_name`, `jmeno`, … — a to i ve vnořených objektech. Počet vstupenek umí i sečíst z pole položek.

Když v prvním reálném oznámení něco chybí, otevřete **Recent webhook calls**, rozklikněte *raw payload* a doplňte cestu k poli do sekce **Field mapping**, např. `data.attributes.show_name` nebo `order.items.0.event.name`.

Další nastavení: **Only notify for** (filtr typů události, např. jen `order.paid`, ať nechodí notifikace o vytvořené nezaplacené objednávce), **Amounts in the smallest unit** (když částky chodí v haléřích) a texty obou šablon s placeholdery `{event} {tickets} {amount} {currency} {buyer} {email} {order_id} {url} {type} {today_tickets} {today_amount} {site} {time}`.

## Když Eventlook webhooky neumí

Endpoint je obyčejný JSON webhook, takže mezi Eventlook a web jde postavit relay:

- **Make.com / Zapier**: trigger *nový e-mail* (potvrzení o prodeji z Eventlooku) → modul *HTTP POST* na webhook URL. Do těla dejte co se z e-mailu vyparsuje, klidně `{"event_name":"…","quantity":…,"total":…}`.
- Jakákoli jiná automatizace, která umí HTTP POST.

## Vývoj

```bash
php eventlook-notifier/tests/test-payload.php
```

Testy parseru běží bez WordPressu a pokrývají ploché i vnořené payloady, sčítání položek, evropský formát částek, ruční mapování a vykreslení šablon.

Rozšíření vlastním kanálem (Slack, e-mail, …):

```php
add_action( 'eln_sale_notified', function ( $sale, $notification, $results ) {
    // $sale['event'], $sale['tickets'], $sale['amount'], …
}, 10, 3 );
```

Text notifikace se dá přepsat filtrem `eln_notification`.

## Bezpečnost

- Endpoint bez nastaveného secretu odmítá vše (503), s nastaveným porovnává token i podpis v konstantním čase.
- Secret, tokeny kanálů i log jsou v `wp_options` mimo autoload, nic se neposílá do prohlížeče.
- Do třetích stran odchází jen text notifikace — na váš ntfy server a/nebo Pushover.
