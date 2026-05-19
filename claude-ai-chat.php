<?php
/**
 * Plugin Name: Claude AI Chat for WordPress
 * Plugin URI:  https://github.com/yourusername/claude-ai-chat-wp
 * Description: Add an AI-powered chat widget to your WordPress site using Anthropic's Claude API. Supports custom system prompts, email escalation, and multi-agent routing.
 * Version:     1.0.0
 * Author:      Your Name
 * Author URI:  https://github.com/yourusername
 * License:     GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: claude-ai-chat
 * Domain Path: /languages
 * Requires at least: 6.0
 * Requires PHP: 8.0
 */

defined( 'ABSPATH' ) || exit;

define( 'CAICW_VERSION',     '1.0.0' );
define( 'CAICW_PLUGIN_DIR',  plugin_dir_path( __FILE__ ) );
define( 'CAICW_PLUGIN_URL',  plugin_dir_url( __FILE__ ) );
define( 'CAICW_PLUGIN_FILE', __FILE__ );

require_once CAICW_PLUGIN_DIR . 'includes/class-caicw-settings.php';
require_once CAICW_PLUGIN_DIR . 'includes/class-caicw-api.php';
require_once CAICW_PLUGIN_DIR . 'includes/class-caicw-widget.php';
require_once CAICW_PLUGIN_DIR . 'includes/class-caicw-email.php';

function caicw_init() {
    CAICW_Settings::init();
    CAICW_Widget::init();
    CAICW_API::init();
}
add_action( 'plugins_loaded', 'caicw_init' );

register_activation_hook( __FILE__, function () {
    add_option( 'caicw_settings', [
        'api_key'       => '',
        'model'         => 'claude-sonnet-4-20250514',
        'system_prompt' => 'You are a helpful assistant on this website. Be friendly, concise, and helpful. If a customer requests human support, collect their name and email and let them know someone will reach out.',
        'widget_title'  => 'Chat with us',
        'accent_color'  => '#2563eb',
        'agents'        => [],
        'enabled_pages' => 'all',
    ] );
} );

register_deactivation_hook( __FILE__, function () {
    wp_clear_scheduled_hook( 'caicw_cleanup' );
} );
