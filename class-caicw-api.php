<?php
defined( 'ABSPATH' ) || exit;

class CAICW_API {

    public static function init() {
        add_action( 'wp_ajax_caicw_chat',        [ __CLASS__, 'handle_chat' ] );
        add_action( 'wp_ajax_nopriv_caicw_chat', [ __CLASS__, 'handle_chat' ] );
    }

    public static function handle_chat() {
        check_ajax_referer( 'caicw_nonce', 'nonce' );

        $messages = isset( $_POST['messages'] ) ? $_POST['messages'] : [];
        $visitor  = [
            'name'  => sanitize_text_field( $_POST['visitor_name'] ?? '' ),
            'email' => sanitize_email( $_POST['visitor_email'] ?? '' ),
        ];

        if ( empty( $messages ) || ! is_array( $messages ) ) {
            wp_send_json_error( [ 'message' => __( 'No messages provided.', 'claude-ai-chat' ) ] );
        }

        $clean_messages = [];
        foreach ( $messages as $msg ) {
            $role    = in_array( $msg['role'] ?? '', [ 'user', 'assistant' ], true ) ? $msg['role'] : 'user';
            $content = sanitize_textarea_field( $msg['content'] ?? '' );
            if ( ! empty( $content ) ) {
                $clean_messages[] = [ 'role' => $role, 'content' => $content ];
            }
        }

        if ( empty( $clean_messages ) ) {
            wp_send_json_error( [ 'message' => __( 'Empty message.', 'claude-ai-chat' ) ] );
        }

        $api_key       = CAICW_Settings::get( 'api_key' );
        $model         = CAICW_Settings::get( 'model' ) ?: 'claude-sonnet-4-20250514';
        $system_prompt = CAICW_Settings::get( 'system_prompt' ) ?: 'You are a helpful assistant.';
        $agents        = CAICW_Settings::get( 'agents' ) ?: [];

        if ( empty( $api_key ) ) {
            wp_send_json_error( [ 'message' => __( 'API key not configured.', 'claude-ai-chat' ) ] );
        }

        $full_system = $system_prompt . self::build_agent_instructions( $agents, $visitor );

        $response = wp_remote_post( 'https://api.anthropic.com/v1/messages', [
            'timeout' => 30,
            'headers' => [
                'x-api-key'         => $api_key,
                'anthropic-version' => '2023-06-01',
                'content-type'      => 'application/json',
            ],
            'body' => wp_json_encode( [
                'model'      => $model,
                'max_tokens' => 1024,
                'system'     => $full_system,
                'messages'   => $clean_messages,
            ] ),
        ] );

        if ( is_wp_error( $response ) ) {
            wp_send_json_error( [ 'message' => $response->get_error_message() ] );
        }

        $body = json_decode( wp_remote_retrieve_body( $response ), true );

        if ( empty( $body['content'][0]['text'] ) ) {
            wp_send_json_error( [ 'message' => __( 'Empty response from Claude.', 'claude-ai-chat' ) ] );
        }

        $reply = $body['content'][0]['text'];

        $escalation = self::detect_escalation( $reply, $clean_messages, $agents );
        if ( $escalation ) {
            CAICW_Email::send_escalation( $escalation['agent'], $visitor, $clean_messages, $reply );
        }

        wp_send_json_success( [
            'reply'     => $reply,
            'escalated' => ! empty( $escalation ),
        ] );
    }

    private static function build_agent_instructions( $agents, $visitor ) {
        if ( empty( $agents ) ) return '';

        $lines = "\n\n---\nAGENT ROUTING INSTRUCTIONS:\n";
        $lines .= "When a customer needs human help, include the exact phrase [ESCALATE] in your response ";
        $lines .= "followed by the agent's topic in square brackets, e.g. [ESCALATE][Solar panels].\n";
        $lines .= "Available agents:\n";

        foreach ( $agents as $agent ) {
            $lines .= sprintf( "- %s (%s): topic=%s, trigger=%s\n",
                $agent['name'], $agent['email'], $agent['topic'], $agent['trigger']
            );
        }

        if ( ! empty( $visitor['name'] ) ) {
            $lines .= "\nCustomer name: " . $visitor['name'];
        }
        if ( ! empty( $visitor['email'] ) ) {
            $lines .= "\nCustomer email: " . $visitor['email'];
        }

        return $lines;
    }

    private static function detect_escalation( $reply, $messages, $agents ) {
        if ( strpos( $reply, '[ESCALATE]' ) === false ) return null;

        foreach ( $agents as $agent ) {
            if ( ! empty( $agent['topic'] ) && strpos( $reply, '[' . $agent['topic'] . ']' ) !== false ) {
                return [ 'agent' => $agent ];
            }
            if ( ! empty( $agent['trigger'] ) ) {
                foreach ( $messages as $msg ) {
                    if ( stripos( $msg['content'], $agent['trigger'] ) !== false ) {
                        return [ 'agent' => $agent ];
                    }
                }
            }
        }

        return [ 'agent' => $agents[0] ];
    }
}
