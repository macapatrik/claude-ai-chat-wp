<?php
defined( 'ABSPATH' ) || exit;

class CAICW_Email {

    public static function send_escalation( $agent, $visitor, $messages, $last_reply ) {
        $to      = $agent['email'];
        $subject = sprintf(
            __( '[New Lead] %s is interested in %s', 'claude-ai-chat' ),
            ! empty( $visitor['name'] ) ? $visitor['name'] : __( 'A visitor', 'claude-ai-chat' ),
            $agent['topic'] ?? __( 'your services', 'claude-ai-chat' )
        );

        $transcript = '';
        foreach ( $messages as $msg ) {
            $label       = $msg['role'] === 'user' ? '👤 Customer' : '🤖 AI';
            $transcript .= $label . ': ' . $msg['content'] . "\n\n";
        }

        $body  = "Hello " . esc_html( $agent['name'] ) . ",\n\n";
        $body .= "A customer from " . get_bloginfo( 'name' ) . " is requesting human support.\n\n";
        $body .= "--- CUSTOMER DETAILS ---\n";
        $body .= "Name:  " . ( $visitor['name']  ?: 'Not provided' ) . "\n";
        $body .= "Email: " . ( $visitor['email'] ?: 'Not provided' ) . "\n\n";
        $body .= "--- AI SUMMARY ---\n";
        $body .= $last_reply . "\n\n";
        $body .= "--- FULL CONVERSATION ---\n";
        $body .= $transcript;
        $body .= "\n---\nThis message was sent automatically by Claude AI Chat plugin.\n";
        $body .= get_bloginfo( 'url' ) . "\n";

        $headers = [ 'Content-Type: text/plain; charset=UTF-8' ];

        if ( ! empty( $visitor['email'] ) ) {
            $headers[] = 'Reply-To: ' . $visitor['name'] . ' <' . $visitor['email'] . '>';
        }

        wp_mail( $to, $subject, $body, $headers );
    }
}
