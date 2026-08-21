<?php
defined( 'ABSPATH' ) || exit;

/**
 * Renders the notification text and pushes it to the enabled channels.
 */
class ELN_Notifier {

    /**
     * @param array $sale Normalized sale (see ELN_Payload::normalize()).
     * @return array<string,array{ok:bool,message:string}> Result per channel, empty when none is enabled.
     */
    public static function dispatch( array $sale ) {
        $s = ELN_Settings::all();

        $notification = apply_filters( 'eln_notification', [
            'title'   => ELN_Payload::render( $s['title_template'], $sale ),
            'message' => ELN_Payload::render( $s['message_template'], $sale ),
            'url'     => $s['ntfy_click_url'] ?: ( $sale['url'] ?? '' ),
        ], $sale );

        if ( $notification['title'] === '' ) {
            $notification['title'] = get_bloginfo( 'name' );
        }
        if ( $notification['message'] === '' ) {
            $notification['message'] = __( 'Ticket sold.', 'eventlook-notifier' );
        }

        $results = [];

        if ( ! empty( $s['ntfy_enabled'] ) ) {
            $results['ntfy'] = self::send_ntfy( $notification, $s );
        }

        if ( ! empty( $s['pushover_enabled'] ) ) {
            $results['pushover'] = self::send_pushover( $notification, $s );
        }

        do_action( 'eln_sale_notified', $sale, $notification, $results );

        return $results;
    }

    private static function send_ntfy( array $notification, array $s ) {
        if ( empty( $s['ntfy_topic'] ) ) {
            return self::fail( __( 'no topic configured', 'eventlook-notifier' ) );
        }

        $body = [
            'topic'    => $s['ntfy_topic'],
            'title'    => $notification['title'],
            'message'  => $notification['message'],
            'priority' => (int) $s['ntfy_priority'],
            'tags'     => [ 'ticket' ],
        ];

        if ( ! empty( $notification['url'] ) ) {
            $body['click'] = $notification['url'];
        }

        $headers = [ 'Content-Type' => 'application/json' ];
        if ( ! empty( $s['ntfy_token'] ) ) {
            $headers['Authorization'] = 'Bearer ' . $s['ntfy_token'];
        }

        // Publishing as JSON to the server root keeps UTF-8 titles intact,
        // which the header-based ntfy API does not.
        $response = wp_remote_post( untrailingslashit( $s['ntfy_server'] ?: 'https://ntfy.sh' ), [
            'timeout' => 10,
            'headers' => $headers,
            'body'    => wp_json_encode( $body ),
        ] );

        return self::interpret( $response );
    }

    private static function send_pushover( array $notification, array $s ) {
        if ( empty( $s['pushover_token'] ) || empty( $s['pushover_user'] ) ) {
            return self::fail( __( 'token or user key missing', 'eventlook-notifier' ) );
        }

        $body = [
            'token'    => $s['pushover_token'],
            'user'     => $s['pushover_user'],
            'title'    => $notification['title'],
            'message'  => $notification['message'],
            'priority' => (int) $s['pushover_priority'],
        ];

        if ( ! empty( $notification['url'] ) ) {
            $body['url'] = $notification['url'];
        }
        if ( ! empty( $s['pushover_sound'] ) ) {
            $body['sound'] = $s['pushover_sound'];
        }
        if ( (int) $s['pushover_priority'] === 2 ) {
            $body['retry']  = 60;
            $body['expire'] = 3600;
        }

        $response = wp_remote_post( 'https://api.pushover.net/1/messages.json', [
            'timeout' => 10,
            'body'    => $body,
        ] );

        return self::interpret( $response );
    }

    private static function interpret( $response ) {
        if ( is_wp_error( $response ) ) {
            return self::fail( $response->get_error_message() );
        }

        $code = (int) wp_remote_retrieve_response_code( $response );
        $body = wp_remote_retrieve_body( $response );

        if ( $code < 200 || $code >= 300 ) {
            return self::fail( sprintf( 'HTTP %d — %s', $code, wp_trim_words( wp_strip_all_tags( $body ), 25 ) ) );
        }

        return [ 'ok' => true, 'message' => '' ];
    }

    private static function fail( $message ) {
        return [ 'ok' => false, 'message' => $message ];
    }
}
