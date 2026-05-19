(function ($) {
  let idx = $('.caicw-agent-row').length;

  $('#caicw-add-agent').on('click', function () {
    const row = `
      <div class="caicw-agent-row">
        <input type="text"  name="caicw_settings[agents][${idx}][name]"    placeholder="Agent name" />
        <input type="email" name="caicw_settings[agents][${idx}][email]"   placeholder="Email" />
        <input type="text"  name="caicw_settings[agents][${idx}][topic]"   placeholder="Topic (e.g. Solar panels)" />
        <input type="text"  name="caicw_settings[agents][${idx}][trigger]" placeholder="Trigger keyword" />
        <button type="button" class="button caicw-remove-agent">Remove</button>
      </div>`;
    $('#caicw-agents-list').append(row);
    idx++;
  });

  $(document).on('click', '.caicw-remove-agent', function () {
    $(this).closest('.caicw-agent-row').remove();
  });
})(jQuery);
