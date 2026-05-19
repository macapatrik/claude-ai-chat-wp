<?php
defined( 'ABSPATH' ) || exit;

class CAICW_Widget {

    public static function init() {
        add_action( 'wp_footer',            [ __CLASS__, 'render_widget' ] );
        add_action( 'wp_enqueue_scripts',   [ __CLASS__, 'enqueue_assets' ] );
    }

    public static function enqueue_assets() {
        if ( ! self::should_show() ) return;

        $settings = CAICW_Settings::get();

        wp_enqueue_style(
            'caicw-widget',
            CAICW_PLUGIN_URL . 'assets/css/widget.css',
            [],
            CAICW_VERSION
        );

        wp_enqueue_script(
            'caicw-widget',
            CAICW_PLUGIN_URL . 'assets/js/widget.js',
            [],
            CAICW_VERSION,
            true
        );

        wp_localize_script( 'caicw-widget', 'caicwData', [
            'ajaxUrl'      => admin_url( 'admin-ajax.php' ),
            'nonce'        => wp_create_nonce( 'caicw_nonce' ),
            'accentColor'  => $settings['accent_color'] ?? '#2563eb',
            'widgetTitle'  => $settings['widget_title']  ?? __( 'Chat with us', 'claude-ai-chat' ),
            'welcomeMsg'   => __( 'Hi! How can I help you today?', 'claude-ai-chat' ),
            'placeholder'  => __( 'Type your message…', 'claude-ai-chat' ),
            'namePlaceholder'  => __( 'Your name', 'claude-ai-chat' ),
            'emailPlaceholder' => __( 'Your email', 'claude-ai-chat' ),
            'startBtn'     => __( 'Start chat', 'claude-ai-chat' ),
            'errorMsg'     => __( 'Something went wrong. Please try again.', 'claude-ai-chat' ),
            'escalatedMsg' => __( 'Our team has been notified and will reach out to you shortly.', 'claude-ai-chat' ),
        ] );
    }

    private static function should_show() {
        $api_key = CAICW_Settings::get( 'api_key' );
        if ( empty( $api_key ) ) return false;

        $enabled = CAICW_Settings::get( 'enabled_pages' );
        if ( $enabled === 'home' && ! is_front_page() ) return false;

        return true;
    }

    public static function render_widget() {
        if ( ! self::should_show() ) return;
        ?>
        <div id="caicw-root" aria-live="polite" role="region" aria-label="<?php esc_attr_e( 'AI Chat Support', 'claude-ai-chat' ); ?>">
        </div>
        <?php
    }
}
