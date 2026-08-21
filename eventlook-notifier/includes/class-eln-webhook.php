<?php
defined( 'ABSPATH' ) || exit;

/**
 * REST endpoint Eventlook (or a Zapier/Make relay) calls on every sale.
 *
 * POST /wp-json/eventlook/v1/sale
 * GET  /wp-json/eventlook/v1/ping   — connectivity check, sends nothing
 */
class ELN_Webhook {

    const NS = 'eventlook/v1';

    const TOKEN_HEADERS = [ 'x_eventlook_token', 'x_webhook_token', 'x_auth_token', 'x_api_key', 'authorization' ];
    const SIG_HEADERS   = [ 'x_eventlook_signature', 'x_signature', 'x_signature_256', 'x_hub_signature_256' ];

    public static function init() {
        add_action( 'rest_api_init', [ __CLASS__, 'register_routes' ] );
    }

    public static function register_routes() {
        register_rest_route( self::NS, '/sale', [
            'methods'             => 'POST',
            'callback'            => [ __CLASS__, 'handle_sale' ],
            'permission_callback' => [ __CLASS__, 'authorize' ],
        ] );

        register_rest_route( self::NS, '/ping', [
            'methods'             => [ 'GET', 'POST' ],
            'callback'            => [ __CLASS__, 'handle_ping' ],
            'permission_callback' => [ __CLASS__, 'authorize' ],
        ] );
    }

    /* ----------------------------------------------------------------- auth */

    public static function authorize( WP_REST_Request $request ) {
        $secret = (string) ELN_Settings::get( 'secret' );

        if ( $secret === '' ) {
            return new WP_Error(
                'eln_not_configured',
                __( 'Eventlook notifier has no secret configured.', 'eventlook-notifier' ),
                [ 'status' => 503 ]
            );
        }

        foreach ( self::token_candidates( $request ) as $candidate ) {
            if ( $candidate !== '' && hash_equals( $secret, $candidate ) ) {
                return true;
            }
        }

        $body = $request->get_body();
        if ( $body !== '' ) {
            $expected = hash_hmac( 'sha256', $body, $secret );

            foreach ( self::SIG_HEADERS as $header ) {
                $given = (string) $request->get_header( $header );
                if ( $given === '' ) {
                    continue;
                }
                $given = trim( str_ireplace( [ 'sha256=', 'hmac-sha256=' ], '', $given ) );
                if ( hash_equals( $expected, strtolower( $given ) ) ) {
                    return true;
                }
            }
        }

        return new WP_Error(
            'eln_unauthorized',
            __( 'Invalid or missing Eventlook webhook token.', 'eventlook-notifier' ),
            [ 'status' => 401 ]
        );
    }

    private static function token_candidates( WP_REST_Request $request ) {
        $candidates = [];

        foreach ( self::TOKEN_HEADERS as $header ) {
            $value = trim( (string) $request->get_header( $header ) );
            if ( $value !== '' ) {
                $candidates[] = preg_replace( '/^(Bearer|Token)\s+/i', '', $value );
            }
        }

        foreach ( [ 'token', 'secret', 'key' ] as $param ) {
            $value = $request->get_param( $param );
            if ( is_string( $value ) && $value !== '' ) {
                $candidates[] = trim( $value );
            }
        }

        return $candidates;
    }

    /* -------------------------------------------------------------- handlers */

    public static function handle_ping() {
        return new WP_REST_Response( [
            'ok'   => true,
            'site' => get_bloginfo( 'name' ),
            'time' => wp_date( 'c' ),
        ], 200 );
    }

    public static function handle_sale( WP_REST_Request $request ) {
        $raw  = $request->get_body();
        $data = self::parse( $request );

        if ( empty( $data ) ) {
            ELN_Log::add( [
                'sale' => [],
                'raw'  => $raw,
                'note' => __( 'empty or unreadable body', 'eventlook-notifier' ),
            ] );

            return new WP_REST_Response( [
                'ok'    => false,
                'error' => __( 'Empty or unreadable payload.', 'eventlook-notifier' ),
            ], 400 );
        }

        // Some senders batch several orders into one call.
        $orders  = self::is_list( $data ) ? $data : [ $data ];
        $notified = 0;
        $skipped  = 0;

        foreach ( $orders as $order ) {
            if ( ! is_array( $order ) ) {
                continue;
            }

            $sale = ELN_Payload::normalize( $order );
            $skip = self::should_skip( $sale );

            if ( $skip ) {
                $skipped++;
                ELN_Log::add( [ 'sale' => $sale, 'raw' => $raw, 'note' => $skip ] );
                continue;
            }

            $today = ELN_Log::add_to_today( $sale['tickets'], $sale['amount_raw'] ?? 0 );

            $sale['today_tickets'] = $today['tickets'];
            $sale['today_amount']  = ELN_Payload::format_amount( $today['amount'] );

            $results = ELN_Notifier::dispatch( $sale );
            $notified++;

            ELN_Log::add( [
                'sale'    => $sale,
                'raw'     => $raw,
                'results' => $results,
                'note'    => empty( $results ) ? __( 'no channel enabled', 'eventlook-notifier' ) : '',
            ] );
        }

        return new WP_REST_Response( [
            'ok'       => true,
            'notified' => $notified,
            'skipped'  => $skipped,
        ], 200 );
    }

    /* --------------------------------------------------------------- helpers */

    /** @return string Reason to skip, or '' to notify. */
    private static function should_skip( array $sale ) {
        $filter = trim( (string) ELN_Settings::get( 'type_filter' ) );

        if ( $filter !== '' && $sale['type'] !== '' ) {
            $allowed = array_filter( array_map( 'trim', explode( ',', strtolower( $filter ) ) ) );

            if ( $allowed && ! in_array( strtolower( $sale['type'] ), $allowed, true ) ) {
                /* translators: %s: event type from the payload. */
                return sprintf( __( 'type "%s" filtered out', 'eventlook-notifier' ), $sale['type'] );
            }
        }

        if ( $sale['order_id'] !== '' ) {
            $key = 'eln_seen_' . md5( $sale['order_id'] );

            if ( get_transient( $key ) ) {
                /* translators: %s: order identifier. */
                return sprintf( __( 'duplicate of order %s', 'eventlook-notifier' ), $sale['order_id'] );
            }

            set_transient( $key, 1, DAY_IN_SECONDS );
        }

        return '';
    }

    private static function parse( WP_REST_Request $request ) {
        $data = $request->get_json_params();

        if ( ! is_array( $data ) || $data === [] ) {
            $data = $request->get_body_params();
        }

        if ( ! is_array( $data ) || $data === [] ) {
            $raw     = $request->get_body();
            $decoded = json_decode( $raw, true );

            if ( is_array( $decoded ) ) {
                $data = $decoded;
            } else {
                parse_str( $raw, $parsed );
                $data = is_array( $parsed ) ? $parsed : [];
            }
        }

        return is_array( $data ) ? $data : [];
    }

    /** array_is_list() equivalent — the plugin still supports PHP 8.0. */
    private static function is_list( array $data ) {
        if ( $data === [] || array_keys( $data ) !== range( 0, count( $data ) - 1 ) ) {
            return false;
        }

        foreach ( $data as $item ) {
            if ( ! is_array( $item ) ) {
                return false;
            }
        }

        return true;
    }
}
