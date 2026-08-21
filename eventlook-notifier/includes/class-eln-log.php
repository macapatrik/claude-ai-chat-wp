<?php
defined( 'ABSPATH' ) || exit;

/**
 * Small ring buffer of recent webhook calls plus the running daily totals.
 * Everything lives in two non-autoloaded options — no custom tables.
 */
class ELN_Log {

    const OPTION_LOG    = 'eln_log';
    const OPTION_TOTALS = 'eln_totals';
    const MAX_ENTRIES   = 25;
    const MAX_RAW       = 4000;

    public static function add( array $entry ) {
        $entry = array_merge( [
            'time'    => time(),
            'source'  => 'webhook',
            'sale'    => [],
            'results' => [],
            'raw'     => '',
            'note'    => '',
        ], $entry );

        if ( ! ELN_Settings::get( 'log_payloads' ) ) {
            $entry['raw'] = '';
        } elseif ( strlen( $entry['raw'] ) > self::MAX_RAW ) {
            $entry['raw'] = substr( $entry['raw'], 0, self::MAX_RAW ) . '…';
        }

        $entries = self::all();
        array_unshift( $entries, $entry );
        update_option( self::OPTION_LOG, array_slice( $entries, 0, self::MAX_ENTRIES ), false );
    }

    public static function all() {
        $entries = get_option( self::OPTION_LOG, [] );
        return is_array( $entries ) ? $entries : [];
    }

    public static function clear() {
        update_option( self::OPTION_LOG, [], false );
    }

    /** @return array{tickets:int,amount:float} Totals for the current day, in site time. */
    public static function today_totals() {
        $totals = get_option( self::OPTION_TOTALS, [] );
        $today  = wp_date( 'Y-m-d' );

        if ( ! is_array( $totals ) || ( $totals['date'] ?? '' ) !== $today ) {
            return [ 'tickets' => 0, 'amount' => 0.0 ];
        }

        return [
            'tickets' => (int) ( $totals['tickets'] ?? 0 ),
            'amount'  => (float) ( $totals['amount'] ?? 0 ),
        ];
    }

    /** Adds one sale to today's totals and returns the updated numbers. */
    public static function add_to_today( $tickets, $amount ) {
        $totals = self::today_totals();

        $totals['tickets'] += max( 0, (int) $tickets );
        $totals['amount']  += (float) $amount;

        update_option( self::OPTION_TOTALS, array_merge( $totals, [ 'date' => wp_date( 'Y-m-d' ) ] ), false );

        return $totals;
    }
}
