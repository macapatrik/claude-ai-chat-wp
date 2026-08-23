<?php
defined( 'ABSPATH' ) || exit;

class ELN_Settings {

    const OPTION = 'eln_settings';
    const PAGE   = 'eventlook-notifier';

    public static function defaults() {
        return [
            'secret'            => '',
            'amount_in_cents'   => 0,
            'default_currency'  => 'CZK',
            'type_filter'       => '',
            'title_template'    => '🎟️ Prodáno {tickets}× {event}',
            'message_template'  => "{amount} {currency} · {buyer}\nDnes celkem: {today_tickets} ks / {today_amount} {currency}",
            'map_order_id'      => '',
            'map_event'         => '',
            'map_tickets'       => '',
            'map_amount'        => '',
            'map_currency'      => '',
            'map_buyer'         => '',
            'map_email'         => '',
            'map_url'           => '',
            'map_type'          => '',
            'ntfy_enabled'      => 0,
            'ntfy_server'       => 'https://ntfy.sh',
            'ntfy_topic'        => '',
            'ntfy_token'        => '',
            'ntfy_priority'     => 4,
            'ntfy_click_url'    => '',
            'pushover_enabled'  => 0,
            'pushover_token'    => '',
            'pushover_user'     => '',
            'pushover_priority' => 0,
            'pushover_sound'    => '',
            'log_payloads'      => 1,
        ];
    }

    public static function install() {
        $existing = get_option( self::OPTION );
        if ( ! is_array( $existing ) ) {
            $existing = [];
        }
        $settings = array_merge( self::defaults(), $existing );
        if ( empty( $settings['secret'] ) ) {
            $settings['secret'] = self::generate_secret();
        }
        update_option( self::OPTION, $settings, false );
    }

    public static function generate_secret() {
        return wp_generate_password( 40, false, false );
    }

    public static function all() {
        $stored = get_option( self::OPTION );
        return array_merge( self::defaults(), is_array( $stored ) ? $stored : [] );
    }

    public static function get( $key, $fallback = null ) {
        $all = self::all();
        return array_key_exists( $key, $all ) ? $all[ $key ] : $fallback;
    }

    public static function update( array $values ) {
        update_option( self::OPTION, array_merge( self::all(), $values ), false );
    }

    public static function webhook_url() {
        return rest_url( ELN_Webhook::NS . '/sale' );
    }

    public static function init() {
        add_action( 'admin_menu',                [ __CLASS__, 'add_menu' ] );
        add_action( 'admin_post_eln_save',       [ __CLASS__, 'handle_save' ] );
        add_action( 'admin_post_eln_regenerate', [ __CLASS__, 'handle_regenerate' ] );
        add_action( 'admin_post_eln_clear_log',  [ __CLASS__, 'handle_clear_log' ] );
        add_action( 'wp_ajax_eln_test',          [ __CLASS__, 'handle_test' ] );
        add_action( 'wp_ajax_eln_sounds',        [ __CLASS__, 'handle_sounds' ] );
        add_action( 'admin_enqueue_scripts',     [ __CLASS__, 'enqueue' ] );
    }

    public static function add_menu() {
        add_options_page(
            __( 'Eventlook Notifications', 'eventlook-notifier' ),
            __( 'Eventlook Notifications', 'eventlook-notifier' ),
            'manage_options',
            self::PAGE,
            [ __CLASS__, 'render_page' ]
        );
    }

    public static function enqueue( $hook ) {
        if ( 'settings_page_' . self::PAGE !== $hook ) {
            return;
        }
        wp_enqueue_style( 'eln-admin', ELN_PLUGIN_URL . 'assets/admin.css', [], ELN_VERSION );
        wp_enqueue_script( 'eln-admin', ELN_PLUGIN_URL . 'assets/admin.js', [], ELN_VERSION, true );
        wp_localize_script( 'eln-admin', 'ELN', [
            'ajaxUrl' => admin_url( 'admin-ajax.php' ),
            'nonce'   => wp_create_nonce( 'eln_test' ),
            'sending' => __( 'Sending…', 'eventlook-notifier' ),
            'test'    => __( 'Send test notification', 'eventlook-notifier' ),
            'copied'  => __( 'Copied!', 'eventlook-notifier' ),
            'loading' => __( 'Loading…', 'eventlook-notifier' ),
            'sounds'  => __( 'Load sounds from Pushover', 'eventlook-notifier' ),
        ] );
    }

    /* ---------------------------------------------------------------- forms */

    private static function guard() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( esc_html__( 'You are not allowed to do this.', 'eventlook-notifier' ) );
        }
    }

    private static function redirect_back( $notice ) {
        wp_safe_redirect( add_query_arg( 'eln_notice', $notice, admin_url( 'options-general.php?page=' . self::PAGE ) ) );
        exit;
    }

    public static function handle_save() {
        self::guard();
        check_admin_referer( 'eln_save' );

        $raw   = wp_unslash( $_POST );
        $clean = [];

        foreach ( [ 'default_currency', 'type_filter', 'title_template', 'ntfy_topic', 'ntfy_token',
                    'pushover_token', 'pushover_user', 'pushover_sound',
                    'map_order_id', 'map_event', 'map_tickets', 'map_amount', 'map_currency',
                    'map_buyer', 'map_email', 'map_url', 'map_type' ] as $key ) {
            $clean[ $key ] = sanitize_text_field( $raw[ $key ] ?? '' );
        }

        $clean['message_template'] = sanitize_textarea_field( $raw['message_template'] ?? '' );
        $clean['ntfy_server']      = esc_url_raw( trim( $raw['ntfy_server'] ?? '' ) ) ?: 'https://ntfy.sh';
        $clean['ntfy_click_url']   = esc_url_raw( trim( $raw['ntfy_click_url'] ?? '' ) );
        $clean['ntfy_priority']    = max( 1, min( 5, (int) ( $raw['ntfy_priority'] ?? 4 ) ) );
        $clean['pushover_priority'] = max( -2, min( 2, (int) ( $raw['pushover_priority'] ?? 0 ) ) );

        foreach ( [ 'ntfy_enabled', 'pushover_enabled', 'amount_in_cents', 'log_payloads' ] as $key ) {
            $clean[ $key ] = empty( $raw[ $key ] ) ? 0 : 1;
        }

        $secret = sanitize_text_field( $raw['secret'] ?? '' );
        if ( $secret !== '' ) {
            $clean['secret'] = $secret;
        }

        self::update( $clean );
        self::redirect_back( 'saved' );
    }

    public static function handle_regenerate() {
        self::guard();
        check_admin_referer( 'eln_regenerate' );
        self::update( [ 'secret' => self::generate_secret() ] );
        self::redirect_back( 'regenerated' );
    }

    public static function handle_clear_log() {
        self::guard();
        check_admin_referer( 'eln_clear_log' );
        ELN_Log::clear();
        self::redirect_back( 'log_cleared' );
    }

    public static function handle_test() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( [ 'message' => __( 'Not allowed.', 'eventlook-notifier' ) ] );
        }
        check_ajax_referer( 'eln_test', 'nonce' );

        $sale    = ELN_Payload::sample();
        $results = ELN_Notifier::dispatch( $sale );

        ELN_Log::add( [
            'source'   => 'test',
            'sale'     => $sale,
            'results'  => $results,
            'raw'      => '',
        ] );

        $failed = array_filter( $results, static fn( $r ) => empty( $r['ok'] ) );

        if ( empty( $results ) ) {
            wp_send_json_error( [ 'message' => __( 'No channel is enabled — turn on ntfy or Pushover first.', 'eventlook-notifier' ) ] );
        }

        if ( $failed ) {
            $messages = [];
            foreach ( $failed as $channel => $result ) {
                $messages[] = $channel . ': ' . $result['message'];
            }
            wp_send_json_error( [ 'message' => implode( ' | ', $messages ) ] );
        }

        wp_send_json_success( [ 'message' => __( 'Test notification sent.', 'eventlook-notifier' ) ] );
    }

    /** Lists the sounds available to the configured Pushover application, custom uploads included. */
    public static function handle_sounds() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( [ 'message' => __( 'Not allowed.', 'eventlook-notifier' ) ] );
        }
        check_ajax_referer( 'eln_test', 'nonce' );

        $token = self::get( 'pushover_token' );

        if ( empty( $token ) ) {
            wp_send_json_error( [ 'message' => __( 'Save your Pushover application token first.', 'eventlook-notifier' ) ] );
        }

        $response = wp_remote_get( add_query_arg( 'token', rawurlencode( $token ), 'https://api.pushover.net/1/sounds.json' ), [ 'timeout' => 10 ] );

        if ( is_wp_error( $response ) ) {
            wp_send_json_error( [ 'message' => $response->get_error_message() ] );
        }

        $body = json_decode( wp_remote_retrieve_body( $response ), true );

        if ( empty( $body['sounds'] ) || ! is_array( $body['sounds'] ) ) {
            wp_send_json_error( [ 'message' => __( 'Pushover returned no sounds — check the application token.', 'eventlook-notifier' ) ] );
        }

        $sounds = [];
        foreach ( $body['sounds'] as $key => $label ) {
            $sounds[ sanitize_text_field( $key ) ] = sanitize_text_field( $label );
        }

        wp_send_json_success( [ 'sounds' => $sounds ] );
    }

    /* ----------------------------------------------------------------- view */

    public static function render_page() {
        self::guard();
        $s      = self::all();
        $notice = isset( $_GET['eln_notice'] ) ? sanitize_key( $_GET['eln_notice'] ) : '';
        $notices = [
            'saved'       => __( 'Settings saved.', 'eventlook-notifier' ),
            'regenerated' => __( 'A new secret was generated — update it in Eventlook too.', 'eventlook-notifier' ),
            'log_cleared' => __( 'Log cleared.', 'eventlook-notifier' ),
        ];
        ?>
        <div class="wrap eln-wrap">
            <h1><?php esc_html_e( 'Eventlook Sale Notifications', 'eventlook-notifier' ); ?></h1>

            <?php if ( isset( $notices[ $notice ] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php echo esc_html( $notices[ $notice ] ); ?></p></div>
            <?php endif; ?>

            <?php if ( empty( $s['secret'] ) ) : ?>
                <div class="notice notice-error"><p><?php esc_html_e( 'No secret is set, so the webhook rejects every request. Generate one below.', 'eventlook-notifier' ); ?></p></div>
            <?php endif; ?>

            <h2><?php esc_html_e( '1. Webhook endpoint', 'eventlook-notifier' ); ?></h2>
            <p class="description"><?php esc_html_e( 'Give this URL to Eventlook (or to Zapier/Make, if you relay their e-mail). The secret can travel as the X-Eventlook-Token header, as an Authorization: Bearer header, as a ?token= query parameter, or as an HMAC-SHA256 body signature in X-Eventlook-Signature / X-Hub-Signature-256.', 'eventlook-notifier' ); ?></p>

            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><?php esc_html_e( 'Webhook URL', 'eventlook-notifier' ); ?></th>
                    <td>
                        <input type="text" class="large-text code" id="eln-url" readonly value="<?php echo esc_attr( self::webhook_url() ); ?>">
                        <button type="button" class="button eln-copy" data-target="#eln-url"><?php esc_html_e( 'Copy', 'eventlook-notifier' ); ?></button>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><?php esc_html_e( 'URL with token', 'eventlook-notifier' ); ?></th>
                    <td>
                        <input type="text" class="large-text code" id="eln-url-token" readonly value="<?php echo esc_attr( add_query_arg( 'token', $s['secret'], self::webhook_url() ) ); ?>">
                        <button type="button" class="button eln-copy" data-target="#eln-url-token"><?php esc_html_e( 'Copy', 'eventlook-notifier' ); ?></button>
                        <p class="description"><?php esc_html_e( 'Use this single-field variant if Eventlook only lets you paste a plain URL.', 'eventlook-notifier' ); ?></p>
                    </td>
                </tr>
            </table>

            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                <?php wp_nonce_field( 'eln_save' ); ?>
                <input type="hidden" name="action" value="eln_save">

                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><label for="eln-secret"><?php esc_html_e( 'Shared secret', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <input type="text" class="regular-text code" id="eln-secret" name="secret" value="<?php echo esc_attr( $s['secret'] ); ?>">
                            <p class="description"><?php esc_html_e( 'Requests without a matching token or signature are rejected with 401.', 'eventlook-notifier' ); ?></p>
                        </td>
                    </tr>
                </table>

                <h2><?php esc_html_e( '2. Where notifications go', 'eventlook-notifier' ); ?></h2>

                <h3>ntfy</h3>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><?php esc_html_e( 'Enabled', 'eventlook-notifier' ); ?></th>
                        <td><label><input type="checkbox" name="ntfy_enabled" value="1" <?php checked( $s['ntfy_enabled'], 1 ); ?>> <?php esc_html_e( 'Send sales to ntfy', 'eventlook-notifier' ); ?></label></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-ntfy-server"><?php esc_html_e( 'Server', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="url" class="regular-text" id="eln-ntfy-server" name="ntfy_server" value="<?php echo esc_attr( $s['ntfy_server'] ); ?>" placeholder="https://ntfy.sh"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-ntfy-topic"><?php esc_html_e( 'Topic', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <input type="text" class="regular-text code" id="eln-ntfy-topic" name="ntfy_topic" value="<?php echo esc_attr( $s['ntfy_topic'] ); ?>" placeholder="vstupenky-3f9a2b">
                            <p class="description"><?php esc_html_e( 'On the public ntfy.sh server anyone who guesses the topic can read it — use a long random name, or set an access token below.', 'eventlook-notifier' ); ?></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-ntfy-token"><?php esc_html_e( 'Access token', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="text" class="regular-text code" id="eln-ntfy-token" name="ntfy_token" value="<?php echo esc_attr( $s['ntfy_token'] ); ?>" placeholder="tk_…"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-ntfy-priority"><?php esc_html_e( 'Priority', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <select id="eln-ntfy-priority" name="ntfy_priority">
                                <?php foreach ( [ 1 => 'min', 2 => 'low', 3 => 'default', 4 => 'high', 5 => 'max' ] as $value => $label ) : ?>
                                    <option value="<?php echo esc_attr( $value ); ?>" <?php selected( (int) $s['ntfy_priority'], $value ); ?>><?php echo esc_html( $label ); ?></option>
                                <?php endforeach; ?>
                            </select>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-ntfy-click"><?php esc_html_e( 'Tap opens', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <input type="url" class="regular-text" id="eln-ntfy-click" name="ntfy_click_url" value="<?php echo esc_attr( $s['ntfy_click_url'] ); ?>" placeholder="https://www.eventlook.net/…">
                            <p class="description"><?php esc_html_e( 'Optional. Leave empty to use the order URL from the payload when it contains one.', 'eventlook-notifier' ); ?></p>
                        </td>
                    </tr>
                </table>

                <h3>Pushover</h3>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><?php esc_html_e( 'Enabled', 'eventlook-notifier' ); ?></th>
                        <td><label><input type="checkbox" name="pushover_enabled" value="1" <?php checked( $s['pushover_enabled'], 1 ); ?>> <?php esc_html_e( 'Send sales to Pushover', 'eventlook-notifier' ); ?></label></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-po-token"><?php esc_html_e( 'Application token', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="text" class="regular-text code" id="eln-po-token" name="pushover_token" value="<?php echo esc_attr( $s['pushover_token'] ); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-po-user"><?php esc_html_e( 'User / group key', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="text" class="regular-text code" id="eln-po-user" name="pushover_user" value="<?php echo esc_attr( $s['pushover_user'] ); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-po-priority"><?php esc_html_e( 'Priority', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <select id="eln-po-priority" name="pushover_priority">
                                <?php foreach ( [ -2 => 'lowest', -1 => 'low', 0 => 'normal', 1 => 'high', 2 => 'emergency' ] as $value => $label ) : ?>
                                    <option value="<?php echo esc_attr( $value ); ?>" <?php selected( (int) $s['pushover_priority'], $value ); ?>><?php echo esc_html( $label ); ?></option>
                                <?php endforeach; ?>
                            </select>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-po-sound"><?php esc_html_e( 'Sound', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <input type="text" class="regular-text code" id="eln-po-sound" name="pushover_sound" value="<?php echo esc_attr( $s['pushover_sound'] ); ?>" placeholder="cashregister">
                            <button type="button" class="button" id="eln-sounds"><?php esc_html_e( 'Load sounds from Pushover', 'eventlook-notifier' ); ?></button>
                            <select id="eln-sound-list" class="eln-sound-list" hidden></select>
                            <p class="description">
                                <?php esc_html_e( 'Leave empty for the Pushover default. Your own jingle: upload an MP3 (max 500 kB, up to 30 s for iOS) at pushover.net → Sounds, then load the list here and pick it — it plays on every phone that receives the notification.', 'eventlook-notifier' ); ?>
                            </p>
                            <span id="eln-sound-result" class="eln-result"></span>
                        </td>
                    </tr>
                </table>

                <h2><?php esc_html_e( '3. Notification text', 'eventlook-notifier' ); ?></h2>
                <table class="form-table" role="presentation">
                    <tr>
                        <th scope="row"><label for="eln-title"><?php esc_html_e( 'Title', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="text" class="large-text" id="eln-title" name="title_template" value="<?php echo esc_attr( $s['title_template'] ); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-message"><?php esc_html_e( 'Message', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <textarea class="large-text code" id="eln-message" name="message_template" rows="4"><?php echo esc_textarea( $s['message_template'] ); ?></textarea>
                            <p class="description">
                                <?php esc_html_e( 'Placeholders:', 'eventlook-notifier' ); ?>
                                <?php echo '<code>' . implode( '</code> <code>', array_map( 'esc_html', ELN_Payload::placeholders() ) ) . '</code>'; // phpcs:ignore WordPress.Security.EscapeOutput ?>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-currency"><?php esc_html_e( 'Default currency', 'eventlook-notifier' ); ?></label></th>
                        <td><input type="text" class="small-text" id="eln-currency" name="default_currency" value="<?php echo esc_attr( $s['default_currency'] ); ?>"></td>
                    </tr>
                    <tr>
                        <th scope="row"><?php esc_html_e( 'Amounts', 'eventlook-notifier' ); ?></th>
                        <td><label><input type="checkbox" name="amount_in_cents" value="1" <?php checked( $s['amount_in_cents'], 1 ); ?>> <?php esc_html_e( 'Payload sends amounts in the smallest unit (haléře/cents) — divide by 100', 'eventlook-notifier' ); ?></label></td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="eln-filter"><?php esc_html_e( 'Only notify for', 'eventlook-notifier' ); ?></label></th>
                        <td>
                            <input type="text" class="regular-text code" id="eln-filter" name="type_filter" value="<?php echo esc_attr( $s['type_filter'] ); ?>" placeholder="order.paid, sale">
                            <p class="description"><?php esc_html_e( 'Comma-separated event types to accept. Leave empty to notify for every request.', 'eventlook-notifier' ); ?></p>
                        </td>
                    </tr>
                </table>

                <h2><?php esc_html_e( '4. Field mapping (optional)', 'eventlook-notifier' ); ?></h2>
                <p class="description"><?php esc_html_e( 'The plugin auto-detects the usual field names. If Eventlook sends something unusual, look at the raw payload in the log below and enter its dot path here, e.g. order.items.0.event.name', 'eventlook-notifier' ); ?></p>
                <table class="form-table" role="presentation">
                    <?php
                    $maps = [
                        'map_event'    => __( 'Event name', 'eventlook-notifier' ),
                        'map_tickets'  => __( 'Ticket count', 'eventlook-notifier' ),
                        'map_amount'   => __( 'Amount', 'eventlook-notifier' ),
                        'map_currency' => __( 'Currency', 'eventlook-notifier' ),
                        'map_buyer'    => __( 'Buyer name', 'eventlook-notifier' ),
                        'map_email'    => __( 'Buyer e-mail', 'eventlook-notifier' ),
                        'map_order_id' => __( 'Order ID', 'eventlook-notifier' ),
                        'map_url'      => __( 'Order URL', 'eventlook-notifier' ),
                        'map_type'     => __( 'Event type', 'eventlook-notifier' ),
                    ];
                    foreach ( $maps as $key => $label ) :
                        ?>
                        <tr>
                            <th scope="row"><label for="eln-<?php echo esc_attr( $key ); ?>"><?php echo esc_html( $label ); ?></label></th>
                            <td><input type="text" class="regular-text code" id="eln-<?php echo esc_attr( $key ); ?>" name="<?php echo esc_attr( $key ); ?>" value="<?php echo esc_attr( $s[ $key ] ); ?>"></td>
                        </tr>
                    <?php endforeach; ?>
                    <tr>
                        <th scope="row"><?php esc_html_e( 'Debug log', 'eventlook-notifier' ); ?></th>
                        <td><label><input type="checkbox" name="log_payloads" value="1" <?php checked( $s['log_payloads'], 1 ); ?>> <?php esc_html_e( 'Store the raw payload of the last 25 requests', 'eventlook-notifier' ); ?></label></td>
                    </tr>
                </table>

                <?php submit_button(); ?>
            </form>

            <p>
                <button type="button" class="button button-secondary" id="eln-test"><?php esc_html_e( 'Send test notification', 'eventlook-notifier' ); ?></button>
                <span id="eln-test-result" class="eln-result"></span>
            </p>

            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" class="eln-inline">
                <?php wp_nonce_field( 'eln_regenerate' ); ?>
                <input type="hidden" name="action" value="eln_regenerate">
                <button type="submit" class="button"><?php esc_html_e( 'Generate a new secret', 'eventlook-notifier' ); ?></button>
            </form>

            <h2><?php esc_html_e( 'Recent webhook calls', 'eventlook-notifier' ); ?></h2>
            <?php self::render_log(); ?>
        </div>
        <?php
    }

    private static function render_log() {
        $entries = ELN_Log::all();

        if ( empty( $entries ) ) {
            echo '<p>' . esc_html__( 'Nothing yet. Once Eventlook calls the webhook, the last 25 requests show up here with their raw payload — handy for fixing the field mapping.', 'eventlook-notifier' ) . '</p>';
            return;
        }
        ?>
        <table class="widefat striped eln-log">
            <thead>
            <tr>
                <th><?php esc_html_e( 'Time', 'eventlook-notifier' ); ?></th>
                <th><?php esc_html_e( 'Source', 'eventlook-notifier' ); ?></th>
                <th><?php esc_html_e( 'Sale', 'eventlook-notifier' ); ?></th>
                <th><?php esc_html_e( 'Delivery', 'eventlook-notifier' ); ?></th>
            </tr>
            </thead>
            <tbody>
            <?php foreach ( $entries as $entry ) : ?>
                <tr>
                    <td><?php echo esc_html( wp_date( 'j.n. H:i:s', $entry['time'] ) ); ?></td>
                    <td><?php echo esc_html( $entry['source'] ); ?></td>
                    <td>
                        <?php
                        $sale = $entry['sale'];
                        echo esc_html( trim( sprintf(
                            '%s× %s — %s %s %s',
                            $sale['tickets'] ?? '?',
                            $sale['event'] ?? '?',
                            $sale['amount'] ?? '?',
                            $sale['currency'] ?? '',
                            ! empty( $sale['buyer'] ) ? '· ' . $sale['buyer'] : ''
                        ) ) );
                        ?>
                        <?php if ( ! empty( $entry['raw'] ) ) : ?>
                            <button type="button" class="button-link eln-toggle"><?php esc_html_e( 'raw payload', 'eventlook-notifier' ); ?></button>
                            <pre class="eln-raw" hidden><?php echo esc_html( $entry['raw'] ); ?></pre>
                        <?php endif; ?>
                    </td>
                    <td>
                        <?php
                        if ( empty( $entry['results'] ) ) {
                            echo '<span class="eln-warn">' . esc_html__( 'skipped', 'eventlook-notifier' ) . '</span>';
                            if ( ! empty( $entry['note'] ) ) {
                                echo ' <span class="description">' . esc_html( $entry['note'] ) . '</span>';
                            }
                        } else {
                            foreach ( $entry['results'] as $channel => $result ) {
                                printf(
                                    '<div class="%s">%s: %s</div>',
                                    empty( $result['ok'] ) ? 'eln-fail' : 'eln-ok',
                                    esc_html( $channel ),
                                    esc_html( empty( $result['ok'] ) ? $result['message'] : __( 'delivered', 'eventlook-notifier' ) )
                                );
                            }
                        }
                        ?>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>

        <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" class="eln-inline">
            <?php wp_nonce_field( 'eln_clear_log' ); ?>
            <input type="hidden" name="action" value="eln_clear_log">
            <button type="submit" class="button"><?php esc_html_e( 'Clear log', 'eventlook-notifier' ); ?></button>
        </form>
        <?php
    }
}
