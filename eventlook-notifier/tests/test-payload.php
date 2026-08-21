<?php
/**
 * Standalone checks for the payload normalizer — no WordPress needed.
 *
 *   php eventlook-notifier/tests/test-payload.php
 *
 * Eventlook's payload shape is not documented publicly, so these cases cover
 * the field-name variants the normalizer is expected to survive.
 */

define( 'ABSPATH', __DIR__ );

function __( $text, $domain = '' ) { return $text; }
function number_format_i18n( $number, $decimals = 0 ) { return number_format( $number, $decimals, ',', ' ' ); }
function wp_date( $format ) { return date( $format ); }
function get_bloginfo( $key ) { return 'Test site'; }

class ELN_Settings {
    public static $overrides = [];

    public static function all() {
        return array_merge( [
            'amount_in_cents'  => 0,
            'default_currency' => 'CZK',
            'map_order_id'     => '',
            'map_event'        => '',
            'map_tickets'      => '',
            'map_amount'       => '',
            'map_currency'     => '',
            'map_buyer'        => '',
            'map_email'        => '',
            'map_url'          => '',
            'map_type'         => '',
        ], self::$overrides );
    }

    public static function get( $key, $fallback = null ) {
        $all = self::all();
        return $all[ $key ] ?? $fallback;
    }
}

class ELN_Log {
    public static function today_totals() { return [ 'tickets' => 0, 'amount' => 0.0 ]; }
}

require_once __DIR__ . '/../includes/class-eln-payload.php';

$failures = 0;
$checks   = 0;

function check( $label, $actual, $expected ) {
    global $failures, $checks;
    $checks++;

    if ( $actual === $expected ) {
        echo "  ok   $label\n";
        return;
    }

    $failures++;
    printf( "  FAIL %s\n       expected: %s\n       actual:   %s\n", $label, var_export( $expected, true ), var_export( $actual, true ) );
}

echo "flat payload\n";
$sale = ELN_Payload::normalize( [
    'event_name' => 'Kapela X — Lucerna',
    'quantity'   => 3,
    'total'      => 1350,
    'currency'   => 'czk',
    'buyer_name' => 'Jana Dvořáková',
    'email'      => 'jana@example.com',
    'order_id'   => 'A-9931',
    'type'       => 'order.paid',
] );
check( 'event', $sale['event'], 'Kapela X — Lucerna' );
check( 'tickets', $sale['tickets'], 3 );
check( 'amount', $sale['amount'], '1 350' );
check( 'currency', $sale['currency'], 'CZK' );
check( 'buyer', $sale['buyer'], 'Jana Dvořáková' );
check( 'order_id', $sale['order_id'], 'A-9931' );
check( 'type', $sale['type'], 'order.paid' );

echo "nested payload, no explicit ticket count\n";
$sale = ELN_Payload::normalize( [
    'type'  => 'sale',
    'order' => [
        'number'   => 'ORD-77',
        'customer' => [ 'first_name' => 'Petr', 'last_name' => 'Malý', 'email' => 'petr@example.com' ],
        'event'    => [ 'title' => 'Vánoční koncert' ],
        'items'    => [
            [ 'ticket_type' => 'Standard', 'quantity' => 2 ],
            [ 'ticket_type' => 'VIP', 'quantity' => 1 ],
        ],
        'total_price' => '1 250,50 Kč',
    ],
] );
check( 'event from nested title', $sale['event'], 'Vánoční koncert' );
check( 'tickets summed from items', $sale['tickets'], 3 );
check( 'european amount parsed', $sale['amount'], '1 250,50' );
check( 'buyer from first + last', $sale['buyer'], 'Petr Malý' );
check( 'email', $sale['email'], 'petr@example.com' );

echo "amounts in the smallest unit\n";
ELN_Settings::$overrides = [ 'amount_in_cents' => 1 ];
$sale = ELN_Payload::normalize( [ 'name' => 'Klub', 'amount' => 69000, 'tickets' => 2 ] );
check( 'divided by 100', $sale['amount'], '690' );
ELN_Settings::$overrides = [];

echo "explicit dot-path mapping wins over auto-detection\n";
ELN_Settings::$overrides = [ 'map_event' => 'data.attributes.show_name', 'map_tickets' => 'data.attributes.seats.0.count' ];
$sale = ELN_Payload::normalize( [
    'name' => 'Wrong name',
    'data' => [ 'attributes' => [ 'show_name' => 'Right name', 'seats' => [ [ 'count' => 4 ] ] ] ],
] );
check( 'event from dot path', $sale['event'], 'Right name' );
check( 'tickets from dot path', $sale['tickets'], 4 );
ELN_Settings::$overrides = [];

echo "missing fields degrade instead of breaking\n";
$sale = ELN_Payload::normalize( [ 'foo' => 'bar' ] );
check( 'event falls back', $sale['event'], 'Unknown event' );
check( 'tickets default to 1', $sale['tickets'], 1 );
check( 'amount stays empty', $sale['amount'], '' );
check( 'currency from settings', $sale['currency'], 'CZK' );

echo "template rendering\n";
$sale = array_merge( ELN_Payload::normalize( [
    'event_name' => 'Kapela X',
    'quantity'   => 2,
    'total'      => 690,
    'buyer_name' => 'Jan Novák',
] ), [ 'today_tickets' => 7, 'today_amount' => '4 830' ] );
check(
    'title',
    ELN_Payload::render( '🎟️ Prodáno {tickets}× {event}', $sale ),
    '🎟️ Prodáno 2× Kapela X'
);
check(
    'message',
    ELN_Payload::render( "{amount} {currency} · {buyer}\nDnes celkem: {today_tickets} ks / {today_amount} {currency}", $sale ),
    "690 CZK · Jan Novák\nDnes celkem: 7 ks / 4 830 CZK"
);
check(
    'empty placeholder leaves no dangling separator',
    ELN_Payload::render( '{amount} {currency} · {buyer}', array_merge( $sale, [ 'buyer' => '' ] ) ),
    '690 CZK'
);

echo "amount parsing\n";
check( 'plain float', ELN_Payload::parse_amount( '690.5' ), 690.5 );
check( 'czech decimal comma', ELN_Payload::parse_amount( '1.250,50' ), 1250.5 );
check( 'currency suffix stripped', ELN_Payload::parse_amount( '690 Kč' ), 690.0 );
check( 'non-numeric', ELN_Payload::parse_amount( 'zdarma' ), null );
check( 'cents', ELN_Payload::parse_amount( '69000', true ), 690.0 );

printf( "\n%d checks, %d failures\n", $checks, $failures );
exit( $failures > 0 ? 1 : 0 );
