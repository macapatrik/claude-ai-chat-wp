<?php
/**
 * End-to-end checks of the webhook against stubbed WordPress functions.
 *
 *   php eventlook-notifier/tests/test-webhook.php
 *
 * Covers authentication, the duplicate guard, the type filter, batched
 * payloads and the JSON that actually leaves for ntfy / Pushover.
 */

define( 'ABSPATH', __DIR__ );
define( 'DAY_IN_SECONDS', 86400 );

$GLOBALS['options']    = [];
$GLOBALS['transients'] = [];
$GLOBALS['requests']   = [];

function __( $text, $domain = '' ) { return $text; }
function get_option( $key, $default = false ) { return $GLOBALS['options'][ $key ] ?? $default; }
function update_option( $key, $value, $autoload = null ) { $GLOBALS['options'][ $key ] = $value; return true; }
function add_option( $key, $value, $d = '', $a = null ) { $GLOBALS['options'][ $key ] = $value; return true; }
function get_transient( $key ) { return $GLOBALS['transients'][ $key ] ?? false; }
function set_transient( $key, $value, $ttl = 0 ) { $GLOBALS['transients'][ $key ] = $value; return true; }
function wp_generate_password( $length = 12 ) { return str_repeat( 'x', $length ); }
function apply_filters( $hook, $value ) { return $value; }
function do_action( $hook, ...$args ) {}
function add_action( $hook, $callback, $priority = 10, $args = 1 ) {}
function register_rest_route( $ns, $route, $args ) {}
function wp_json_encode( $data ) { return json_encode( $data, JSON_UNESCAPED_UNICODE ); }
function is_wp_error( $thing ) { return $thing instanceof WP_Error; }
function untrailingslashit( $url ) { return rtrim( $url, '/' ); }
function wp_date( $format ) { return date( $format ); }
function number_format_i18n( $number, $decimals = 0 ) { return number_format( $number, $decimals, ',', ' ' ); }
function get_bloginfo( $key ) { return 'Test site'; }
function wp_strip_all_tags( $text ) { return strip_tags( $text ); }
function wp_trim_words( $text, $words = 55 ) { return $text; }
function wp_remote_retrieve_response_code( $response ) { return $response['response']['code']; }
function wp_remote_retrieve_body( $response ) { return $response['body']; }

function wp_remote_post( $url, $args = [] ) {
    $GLOBALS['requests'][] = [ 'url' => $url, 'args' => $args ];
    return [ 'response' => [ 'code' => $GLOBALS['next_status'] ?? 200 ], 'body' => '{"id":"1"}' ];
}

class WP_Error {
    public $code;
    public $data;
    public function __construct( $code = '', $message = '', $data = [] ) {
        $this->code = $code;
        $this->data = $data;
    }
    public function get_error_message() { return 'error'; }
}

class WP_REST_Response {
    public $data;
    public $status;
    public function __construct( $data, $status = 200 ) {
        $this->data   = $data;
        $this->status = $status;
    }
}

class WP_REST_Request {
    private $headers;
    private $body;
    private $query;

    public function __construct( $body = '', array $headers = [], array $query = [] ) {
        $this->body    = $body;
        $this->query   = $query;
        $this->headers = [];
        foreach ( $headers as $name => $value ) {
            $this->headers[ strtolower( str_replace( '-', '_', $name ) ) ] = $value;
        }
    }

    public function get_header( $name ) { return $this->headers[ strtolower( str_replace( '-', '_', $name ) ) ] ?? null; }
    public function get_body() { return $this->body; }
    public function get_json_params() { $decoded = json_decode( $this->body, true ); return is_array( $decoded ) ? $decoded : null; }
    public function get_body_params() { return []; }
    public function get_param( $key ) { return $this->query[ $key ] ?? null; }
}

require_once __DIR__ . '/../includes/class-eln-settings.php';
require_once __DIR__ . '/../includes/class-eln-payload.php';
require_once __DIR__ . '/../includes/class-eln-log.php';
require_once __DIR__ . '/../includes/class-eln-notifier.php';
require_once __DIR__ . '/../includes/class-eln-webhook.php';

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

function reset_state( array $settings = [] ) {
    $GLOBALS['options']    = [];
    $GLOBALS['transients'] = [];
    $GLOBALS['requests']   = [];
    ELN_Settings::install();
    ELN_Settings::update( array_merge( [
        'secret'       => 'topsecret',
        'ntfy_enabled' => 1,
        'ntfy_topic'   => 'vstupenky-test',
    ], $settings ) );
}

const SALE_JSON = '{"type":"order.paid","order_id":"A-1","event_name":"Kapela X","quantity":2,"total":690,"currency":"CZK","buyer_name":"Jan Novák"}';

echo "authentication\n";
reset_state( [ 'secret' => '' ] );
$result = ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON ) );
check( 'no secret configured → 503', $result instanceof WP_Error ? $result->data['status'] : null, 503 );

reset_state();
check( 'no credentials → 401', ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON ) )->data['status'], 401 );
check( 'wrong token → 401', ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [ 'X-Eventlook-Token' => 'nope' ] ) )->data['status'], 401 );
check( 'token header', ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [ 'X-Eventlook-Token' => 'topsecret' ] ) ), true );
check( 'bearer header', ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [ 'Authorization' => 'Bearer topsecret' ] ) ), true );
check( 'query token', ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [], [ 'token' => 'topsecret' ] ) ), true );
check(
    'hmac signature',
    ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [ 'X-Hub-Signature-256' => 'sha256=' . hash_hmac( 'sha256', SALE_JSON, 'topsecret' ) ] ) ),
    true
);
check(
    'hmac over a different body → 401',
    ELN_Webhook::authorize( new WP_REST_Request( SALE_JSON, [ 'X-Eventlook-Signature' => hash_hmac( 'sha256', '{}', 'topsecret' ) ] ) )->data['status'],
    401
);

echo "delivery\n";
reset_state();
$response = ELN_Webhook::handle_sale( new WP_REST_Request( SALE_JSON ) );
check( 'notified once', $response->data['notified'], 1 );
check( 'one outgoing request', count( $GLOBALS['requests'] ), 1 );

$sent = json_decode( $GLOBALS['requests'][0]['args']['body'], true );
check( 'ntfy topic', $sent['topic'], 'vstupenky-test' );
check( 'ntfy title', $sent['title'], '🎟️ Prodáno 2× Kapela X' );
check( 'ntfy message', $sent['message'], "690 CZK · Jan Novák\nDnes celkem: 2 ks / 690 CZK" );
check( 'ntfy priority', $sent['priority'], 4 );

echo "daily totals accumulate\n";
$GLOBALS['requests'] = [];
ELN_Webhook::handle_sale( new WP_REST_Request( str_replace( 'A-1', 'A-2', SALE_JSON ) ) );
$sent = json_decode( $GLOBALS['requests'][0]['args']['body'], true );
check( 'second sale adds up', $sent['message'], "690 CZK · Jan Novák\nDnes celkem: 4 ks / 1 380 CZK" );

echo "duplicate order is dropped\n";
$GLOBALS['requests'] = [];
$response = ELN_Webhook::handle_sale( new WP_REST_Request( SALE_JSON ) );
check( 'skipped', $response->data['skipped'], 1 );
check( 'nothing sent', count( $GLOBALS['requests'] ), 0 );

echo "type filter\n";
reset_state( [ 'type_filter' => 'order.paid' ] );
$response = ELN_Webhook::handle_sale( new WP_REST_Request( str_replace( 'order.paid', 'order.created', SALE_JSON ) ) );
check( 'other type skipped', $response->data['skipped'], 1 );
check( 'nothing sent', count( $GLOBALS['requests'] ), 0 );
$response = ELN_Webhook::handle_sale( new WP_REST_Request( SALE_JSON ) );
check( 'matching type notified', $response->data['notified'], 1 );

echo "batched payload\n";
reset_state();
$batch = '[' . SALE_JSON . ',' . str_replace( 'A-1', 'A-2', SALE_JSON ) . ']';
$response = ELN_Webhook::handle_sale( new WP_REST_Request( $batch ) );
check( 'both orders notified', $response->data['notified'], 2 );
check( 'two outgoing requests', count( $GLOBALS['requests'] ), 2 );

echo "empty and broken bodies\n";
reset_state();
$response = ELN_Webhook::handle_sale( new WP_REST_Request( '' ) );
check( 'empty body → 400', $response->status, 400 );
check( 'nothing sent', count( $GLOBALS['requests'] ), 0 );

echo "channel errors are reported, not thrown\n";
reset_state( [ 'pushover_enabled' => 1, 'pushover_token' => 'a', 'pushover_user' => 'b' ] );
$GLOBALS['next_status'] = 400;
ELN_Webhook::handle_sale( new WP_REST_Request( SALE_JSON ) );
$GLOBALS['next_status'] = 200;
$log = ELN_Log::all();
check( 'both channels attempted', array_keys( $log[0]['results'] ), [ 'ntfy', 'pushover' ] );
check( 'failure recorded', $log[0]['results']['ntfy']['ok'], false );
check( 'raw payload kept for debugging', $log[0]['raw'], SALE_JSON );

echo "pushover payload\n";
reset_state( [ 'ntfy_enabled' => 0, 'pushover_enabled' => 1, 'pushover_token' => 'app-token', 'pushover_user' => 'user-key' ] );
ELN_Webhook::handle_sale( new WP_REST_Request( SALE_JSON ) );
$request = $GLOBALS['requests'][0];
check( 'endpoint', $request['url'], 'https://api.pushover.net/1/messages.json' );
check( 'token', $request['args']['body']['token'], 'app-token' );
check( 'user', $request['args']['body']['user'], 'user-key' );
check( 'title', $request['args']['body']['title'], '🎟️ Prodáno 2× Kapela X' );

printf( "\n%d checks, %d failures\n", $checks, $failures );
exit( $failures > 0 ? 1 : 0 );
