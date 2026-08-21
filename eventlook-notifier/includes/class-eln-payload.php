<?php
defined( 'ABSPATH' ) || exit;

/**
 * Turns whatever JSON Eventlook posts into a flat, predictable sale array.
 *
 * The exact field names Eventlook uses are not documented publicly, so every
 * field is looked up by a list of aliases (breadth-first, so shallow keys win)
 * and can be overridden with an explicit dot path in the settings.
 */
class ELN_Payload {

    const ALIASES = [
        'order_id' => [ 'order_id', 'ordernumber', 'order_number', 'orderid', 'transaction_id', 'purchase_id',
                        'objednavka', 'cislo_objednavky', 'variable_symbol', 'reference', 'code', 'uuid', 'id' ],
        'event'    => [ 'event_name', 'eventname', 'event_title', 'nazev_akce', 'akce', 'nazev', 'event', 'show',
                        'performance', 'concert', 'title', 'name' ],
        'tickets'  => [ 'ticket_count', 'tickets_count', 'ticketcount', 'pocet_vstupenek', 'pocet', 'quantity',
                        'qty', 'tickets', 'count' ],
        'amount'   => [ 'total_price', 'totalprice', 'total_amount', 'grand_total', 'celkova_cena', 'celkem',
                        'castka', 'cena', 'total', 'amount', 'price', 'sum' ],
        'currency' => [ 'currency_code', 'currencycode', 'currency', 'mena' ],
        'buyer'    => [ 'buyer_name', 'customer_name', 'full_name', 'fullname', 'jmeno', 'buyer', 'customer',
                        'purchaser', 'name' ],
        'email'    => [ 'buyer_email', 'customer_email', 'contact_email', 'email' ],
        'url'      => [ 'order_url', 'detail_url', 'admin_url', 'link', 'url' ],
        'type'     => [ 'event_type', 'eventtype', 'webhook_type', 'action', 'type', 'status', 'state' ],
    ];

    const ITEM_KEYS = [ 'items', 'order_items', 'orderitems', 'tickets', 'positions', 'lines', 'polozky' ];

    public static function placeholders() {
        return [
            '{event}', '{tickets}', '{amount}', '{currency}', '{buyer}', '{email}',
            '{order_id}', '{url}', '{type}', '{today_tickets}', '{today_amount}', '{site}', '{time}',
        ];
    }

    /**
     * @param array $data Decoded webhook payload.
     * @return array Normalized sale.
     */
    public static function normalize( $data ) {
        $s = ELN_Settings::all();

        // Line items are searched separately: a per-item "quantity" must not be
        // mistaken for the order's ticket count, nor an item price for the total.
        $without_items = self::strip_items( $data );

        $sale = [];
        foreach ( self::ALIASES as $field => $aliases ) {
            $custom = trim( (string) ( $s[ 'map_' . $field ] ?? '' ) );
            $value  = $custom !== '' ? self::get_path( $data, $custom ) : self::find( $without_items, $aliases );

            if ( $custom === '' && ! is_scalar( $value ) ) {
                $value = self::find( $data, $aliases );
            }

            $sale[ $field ] = is_scalar( $value ) ? trim( (string) $value ) : '';
        }

        // The buyer may arrive split into first/last name.
        if ( $sale['buyer'] === '' ) {
            $first = self::find( $data, [ 'first_name', 'firstname', 'given_name', 'jmeno' ] );
            $last  = self::find( $data, [ 'last_name', 'lastname', 'family_name', 'surname', 'prijmeni' ] );
            $sale['buyer'] = trim( (string) $first . ' ' . (string) $last );
        }

        if ( trim( (string) ( $s['map_tickets'] ?? '' ) ) === '' ) {
            $counted = self::count_items( $data );

            // An explicit order-level count wins; otherwise sum the line items.
            if ( $counted !== null && ( $sale['tickets'] === '' || ! is_numeric( $sale['tickets'] ) || $counted > (int) $sale['tickets'] ) ) {
                $sale['tickets'] = (string) $counted;
            }
        }

        if ( $sale['tickets'] === '' || ! is_numeric( $sale['tickets'] ) ) {
            $sale['tickets'] = '1';
        }

        $amount = self::parse_amount( $sale['amount'], ! empty( $s['amount_in_cents'] ) );

        $sale['tickets']    = max( 1, (int) $sale['tickets'] );
        $sale['amount_raw'] = $amount;
        $sale['amount']     = $amount === null ? '' : self::format_amount( $amount );
        $sale['currency']   = strtoupper( $sale['currency'] ) ?: $s['default_currency'];
        $sale['event']      = $sale['event'] ?: __( 'Unknown event', 'eventlook-notifier' );
        $sale['site']       = get_bloginfo( 'name' );
        $sale['time']       = wp_date( 'H:i' );

        return $sale;
    }

    /** Breadth-first lookup of the first key matching one of $aliases. */
    public static function find( $data, array $aliases ) {
        if ( ! is_array( $data ) ) {
            return null;
        }

        $levels = [ $data ];

        while ( $levels ) {
            $next = [];

            foreach ( $aliases as $alias ) {
                foreach ( $levels as $level ) {
                    foreach ( $level as $key => $value ) {
                        if ( is_scalar( $value ) && $value !== '' && self::key_matches( $key, $alias ) ) {
                            return $value;
                        }
                    }
                }
            }

            foreach ( $levels as $level ) {
                foreach ( $level as $value ) {
                    if ( is_array( $value ) ) {
                        $next[] = $value;
                    }
                }
            }

            $levels = $next;
        }

        return null;
    }

    private static function key_matches( $key, $alias ) {
        $key = strtolower( str_replace( [ '-', ' ' ], '_', (string) $key ) );
        return $key === $alias || $key === str_replace( '_', '', $alias );
    }

    /** Reads a value by dot path, e.g. "order.items.0.event.name". */
    public static function get_path( $data, $path ) {
        foreach ( explode( '.', $path ) as $segment ) {
            if ( ! is_array( $data ) || ! array_key_exists( $segment, $data ) ) {
                return null;
            }
            $data = $data[ $segment ];
        }

        return $data;
    }

    /** Sums the quantities of a line-item array, or null when the payload has none. */
    private static function count_items( $data ) {
        foreach ( self::ITEM_KEYS as $key ) {
            $items = self::find_array( $data, $key );
            if ( $items === null ) {
                continue;
            }

            $total = 0;
            foreach ( $items as $item ) {
                if ( is_array( $item ) ) {
                    $qty    = self::find( $item, [ 'quantity', 'qty', 'count', 'pocet' ] );
                    $total += is_numeric( $qty ) ? (int) $qty : 1;
                } else {
                    $total++;
                }
            }

            if ( $total > 0 ) {
                return $total;
            }
        }

        return null;
    }

    /** Returns a copy of the payload with line-item arrays removed. */
    private static function strip_items( $data ) {
        if ( ! is_array( $data ) ) {
            return $data;
        }

        $copy = [];
        foreach ( $data as $key => $value ) {
            $is_item_list = is_array( $value ) && self::matches_any( $key, self::ITEM_KEYS );

            if ( $is_item_list ) {
                continue;
            }

            $copy[ $key ] = is_array( $value ) ? self::strip_items( $value ) : $value;
        }

        return $copy;
    }

    private static function matches_any( $key, array $needles ) {
        foreach ( $needles as $needle ) {
            if ( self::key_matches( $key, $needle ) ) {
                return true;
            }
        }

        return false;
    }

    private static function find_array( $data, $needle ) {
        if ( ! is_array( $data ) ) {
            return null;
        }

        foreach ( $data as $key => $value ) {
            if ( is_array( $value ) && $value !== [] && self::key_matches( $key, $needle ) ) {
                return $value;
            }
        }

        foreach ( $data as $value ) {
            $found = self::find_array( $value, $needle );
            if ( $found !== null ) {
                return $found;
            }
        }

        return null;
    }

    /** "1 250,50 Kč" / "1250.5" / 125050 → float, or null when not a number. */
    public static function parse_amount( $value, $in_cents = false ) {
        if ( $value === '' || $value === null ) {
            return null;
        }

        $clean = preg_replace( '/[^0-9,.\-]/u', '', (string) $value );

        if ( $clean === '' || $clean === '-' ) {
            return null;
        }

        // Czech/European format: comma is the decimal separator, dot groups thousands.
        if ( strpos( $clean, ',' ) !== false ) {
            $clean = str_replace( [ '.', ',' ], [ '', '.' ], $clean );
        }

        $amount = (float) $clean;

        return $in_cents ? $amount / 100 : $amount;
    }

    public static function format_amount( $amount ) {
        $decimals = ( abs( $amount - round( $amount ) ) < 0.005 ) ? 0 : 2;
        return number_format_i18n( $amount, $decimals );
    }

    public static function render( $template, array $sale ) {
        $replacements = [];
        foreach ( $sale as $key => $value ) {
            if ( is_scalar( $value ) ) {
                $replacements[ '{' . $key . '}' ] = (string) $value;
            }
        }

        $rendered = strtr( (string) $template, $replacements );

        // Drop placeholders we have no value for, then tidy the leftover separators.
        $rendered = preg_replace( '/\{[a-z_]+\}/', '', $rendered );
        $rendered = preg_replace( '/[ \t]*·[ \t]*(\n|$)/u', '$1', $rendered );
        $rendered = preg_replace( '/[ \t]{2,}/', ' ', $rendered );

        return trim( $rendered );
    }

    public static function sample() {
        $today = ELN_Log::today_totals();

        return [
            'order_id'      => 'TEST-1234',
            'event'         => __( 'Test concert', 'eventlook-notifier' ),
            'tickets'       => 2,
            'amount'        => self::format_amount( 690 ),
            'amount_raw'    => 690.0,
            'currency'      => ELN_Settings::get( 'default_currency', 'CZK' ),
            'buyer'         => 'Jan Novák',
            'email'         => 'jan@example.com',
            'url'           => '',
            'type'          => 'test',
            'site'          => get_bloginfo( 'name' ),
            'time'          => wp_date( 'H:i' ),
            'today_tickets' => $today['tickets'],
            'today_amount'  => self::format_amount( $today['amount'] ),
        ];
    }
}
