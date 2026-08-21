<?php
/**
 * Plugin Name: Eventlook Sale Notifications
 * Plugin URI:  https://github.com/macapatrik/claude-ai-chat-wp
 * Description: Receives a webhook from Eventlook whenever a ticket is sold and pushes an instant notification to your team's phones via ntfy and/or Pushover.
 * Version:     1.0.0
 * Author:      Patrik Maca
 * License:     GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: eventlook-notifier
 * Requires at least: 6.0
 * Requires PHP: 8.0
 */

defined( 'ABSPATH' ) || exit;

define( 'ELN_VERSION',     '1.0.0' );
define( 'ELN_PLUGIN_DIR',  plugin_dir_path( __FILE__ ) );
define( 'ELN_PLUGIN_URL',  plugin_dir_url( __FILE__ ) );
define( 'ELN_PLUGIN_FILE', __FILE__ );

require_once ELN_PLUGIN_DIR . 'includes/class-eln-settings.php';
require_once ELN_PLUGIN_DIR . 'includes/class-eln-payload.php';
require_once ELN_PLUGIN_DIR . 'includes/class-eln-log.php';
require_once ELN_PLUGIN_DIR . 'includes/class-eln-notifier.php';
require_once ELN_PLUGIN_DIR . 'includes/class-eln-webhook.php';

function eln_init() {
    ELN_Settings::init();
    ELN_Webhook::init();
}
add_action( 'plugins_loaded', 'eln_init' );

register_activation_hook( __FILE__, [ 'ELN_Settings', 'install' ] );
