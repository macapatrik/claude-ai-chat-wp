<?php
defined( 'ABSPATH' ) || exit;

class CAICW_Settings {

    public static function init() {
        add_action( 'admin_menu',            [ __CLASS__, 'add_menu' ] );
        add_action( 'admin_init',            [ __CLASS__, 'register_settings' ] );
        add_action( 'admin_enqueue_scripts', [ __CLASS__, 'enqueue_admin_assets' ] );
    }

    public static function add_menu() {
        add_options_page(
            __( 'Claude AI Chat', 'claude-ai-chat' ),
            __( 'Claude AI Chat', 'claude-ai-chat' ),
            'manage_options',
            'claude-ai-chat',
            [ __CLASS__, 'render_settings_page' ]
        );
    }

    public static function register_settings() {
        register_setting( 'caicw_settings_group', 'caicw_settings', [
            'sanitize_callback' => [ __CLASS__, 'sanitize_settings' ],
        ] );
    }

    public static function sanitize_settings( $input ) {
        $clean = [];
        $clean['api_key']       = sanitize_text_field( $input['api_key'] ?? '' );
        $clean['model']         = sanitize_text_field( $input['model'] ?? 'claude-sonnet-4-20250514' );
        $clean['system_prompt'] = sanitize_textarea_field( $input['system_prompt'] ?? '' );
        $clean['widget_title']  = sanitize_text_field( $input['widget_title'] ?? 'Chat with us' );
        $clean['accent_color']  = sanitize_hex_color( $input['accent_color'] ?? '#2563eb' );
        $clean['enabled_pages'] = sanitize_text_field( $input['enabled_pages'] ?? 'all' );

        $agents = [];
        if ( ! empty( $input['agents'] ) && is_array( $input['agents'] ) ) {
            foreach ( $input['agents'] as $agent ) {
                if ( ! empty( $agent['name'] ) && ! empty( $agent['email'] ) ) {
                    $agents[] = [
                        'name'    => sanitize_text_field( $agent['name'] ),
                        'email'   => sanitize_email( $agent['email'] ),
                        'topic'   => sanitize_text_field( $agent['topic'] ?? '' ),
                        'trigger' => sanitize_text_field( $agent['trigger'] ?? '' ),
                    ];
                }
            }
        }
        $clean['agents'] = $agents;

        return $clean;
    }

    public static function get( $key = null ) {
        $settings = get_option( 'caicw_settings', [] );
        if ( $key ) {
            return $settings[ $key ] ?? null;
        }
        return $settings;
    }

    public static function enqueue_admin_assets( $hook ) {
        if ( $hook !== 'settings_page_claude-ai-chat' ) return;
        wp_enqueue_style(
            'caicw-admin',
            CAICW_PLUGIN_URL . 'assets/css/admin.css',
            [],
            CAICW_VERSION
        );
        wp_enqueue_script(
            'caicw-admin',
            CAICW_PLUGIN_URL . 'assets/js/admin.js',
            [ 'jquery' ],
            CAICW_VERSION,
            true
        );
    }

    public static function render_settings_page() {
        $settings = self::get();
        $agents   = $settings['agents'] ?? [];
        ?>
        <div class="wrap caicw-settings-wrap">
            <h1><?php esc_html_e( 'Claude AI Chat Settings', 'claude-ai-chat' ); ?></h1>

            <?php if ( empty( $settings['api_key'] ) ) : ?>
                <div class="notice notice-warning">
                    <p><?php esc_html_e( 'Please add your Anthropic API key to activate the chat widget.', 'claude-ai-chat' ); ?></p>
                </div>
            <?php endif; ?>

            <form method="post" action="options.php">
                <?php settings_fields( 'caicw_settings_group' ); ?>

                <div class="caicw-card">
                    <h2><?php esc_html_e( 'API Configuration', 'claude-ai-chat' ); ?></h2>
                    <table class="form-table">
                        <tr>
                            <th><?php esc_html_e( 'Anthropic API Key', 'claude-ai-chat' ); ?></th>
                            <td>
                                <input type="password" name="caicw_settings[api_key]"
                                       value="<?php echo esc_attr( $settings['api_key'] ?? '' ); ?>"
                                       class="regular-text" autocomplete="off" />
                                <p class="description">
                                    <?php printf(
                                        esc_html__( 'Get your key at %s', 'claude-ai-chat' ),
                                        '<a href="https://console.anthropic.com" target="_blank">console.anthropic.com</a>'
                                    ); ?>
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <th><?php esc_html_e( 'Model', 'claude-ai-chat' ); ?></th>
                            <td>
                                <select name="caicw_settings[model]">
                                    <?php
                                    $models = [
                                        'claude-sonnet-4-20250514' => 'Claude Sonnet 4 (recommended)',
                                        'claude-opus-4-5'          => 'Claude Opus 4.5 (most capable)',
                                        'claude-haiku-4-5-20251001'=> 'Claude Haiku 4.5 (fastest)',
                                    ];
                                    foreach ( $models as $value => $label ) {
                                        printf(
                                            '<option value="%s" %s>%s</option>',
                                            esc_attr( $value ),
                                            selected( $settings['model'] ?? '', $value, false ),
                                            esc_html( $label )
                                        );
                                    }
                                    ?>
                                </select>
                            </td>
                        </tr>
                    </table>
                </div>

                <div class="caicw-card">
                    <h2><?php esc_html_e( 'Widget Settings', 'claude-ai-chat' ); ?></h2>
                    <table class="form-table">
                        <tr>
                            <th><?php esc_html_e( 'Widget Title', 'claude-ai-chat' ); ?></th>
                            <td>
                                <input type="text" name="caicw_settings[widget_title]"
                                       value="<?php echo esc_attr( $settings['widget_title'] ?? 'Chat with us' ); ?>"
                                       class="regular-text" />
                            </td>
                        </tr>
                        <tr>
                            <th><?php esc_html_e( 'Accent Color', 'claude-ai-chat' ); ?></th>
                            <td>
                                <input type="color" name="caicw_settings[accent_color]"
                                       value="<?php echo esc_attr( $settings['accent_color'] ?? '#2563eb' ); ?>" />
                            </td>
                        </tr>
                        <tr>
                            <th><?php esc_html_e( 'Show on', 'claude-ai-chat' ); ?></th>
                            <td>
                                <select name="caicw_settings[enabled_pages]">
                                    <option value="all" <?php selected( $settings['enabled_pages'] ?? 'all', 'all' ); ?>>
                                        <?php esc_html_e( 'All pages', 'claude-ai-chat' ); ?>
                                    </option>
                                    <option value="home" <?php selected( $settings['enabled_pages'] ?? '', 'home' ); ?>>
                                        <?php esc_html_e( 'Homepage only', 'claude-ai-chat' ); ?>
                                    </option>
                                </select>
                            </td>
                        </tr>
                    </table>
                </div>

                <div class="caicw-card">
                    <h2><?php esc_html_e( 'System Prompt', 'claude-ai-chat' ); ?></h2>
                    <p class="description">
                        <?php esc_html_e( 'This is the AI agent\'s personality and knowledge base. Add everything about your company, services, FAQ, and pricing.', 'claude-ai-chat' ); ?>
                    </p>
                    <textarea name="caicw_settings[system_prompt]" rows="12" class="large-text"><?php
                        echo esc_textarea( $settings['system_prompt'] ?? '' );
                    ?></textarea>
                </div>

                <div class="caicw-card">
                    <h2><?php esc_html_e( 'Human Agents (Escalation Routing)', 'claude-ai-chat' ); ?></h2>
                    <p class="description">
                        <?php esc_html_e( 'When the AI detects a customer needs human help, it will send an email summary to the right person.', 'claude-ai-chat' ); ?>
                    </p>

                    <div id="caicw-agents-list">
                        <?php foreach ( $agents as $i => $agent ) : ?>
                            <div class="caicw-agent-row">
                                <input type="text" name="caicw_settings[agents][<?php echo $i; ?>][name]"
                                       value="<?php echo esc_attr( $agent['name'] ); ?>"
                                       placeholder="<?php esc_attr_e( 'Agent name', 'claude-ai-chat' ); ?>" />
                                <input type="email" name="caicw_settings[agents][<?php echo $i; ?>][email]"
                                       value="<?php echo esc_attr( $agent['email'] ); ?>"
                                       placeholder="<?php esc_attr_e( 'Email', 'claude-ai-chat' ); ?>" />
                                <input type="text" name="caicw_settings[agents][<?php echo $i; ?>][topic]"
                                       value="<?php echo esc_attr( $agent['topic'] ); ?>"
                                       placeholder="<?php esc_attr_e( 'Topic (e.g. Solar panels)', 'claude-ai-chat' ); ?>" />
                                <input type="text" name="caicw_settings[agents][<?php echo $i; ?>][trigger]"
                                       value="<?php echo esc_attr( $agent['trigger'] ); ?>"
                                       placeholder="<?php esc_attr_e( 'Trigger keyword', 'claude-ai-chat' ); ?>" />
                                <button type="button" class="button caicw-remove-agent">
                                    <?php esc_html_e( 'Remove', 'claude-ai-chat' ); ?>
                                </button>
                            </div>
                        <?php endforeach; ?>
                    </div>

                    <button type="button" class="button" id="caicw-add-agent">
                        + <?php esc_html_e( 'Add Agent', 'claude-ai-chat' ); ?>
                    </button>
                </div>

                <?php submit_button( __( 'Save Settings', 'claude-ai-chat' ) ); ?>
            </form>
        </div>
        <?php
    }
}
