<script>
  /** Small square platform badge. Text initials, never an emoji. */
  let { platform, size = 22 } = $props();

  const initials = {
    youtube: 'YT',
    instagram: 'IG',
    tiktok: 'TT',
    twitter: 'X',
    facebook: 'FB',
  };

  const letter = $derived(initials[platform] || (platform ? platform[0].toUpperCase() : '?'));
</script>

<span
  class="platform-mark {platform}"
  style="width:{size}px;height:{size}px"
  title={platform}
  aria-hidden="true"
>{letter}</span>
