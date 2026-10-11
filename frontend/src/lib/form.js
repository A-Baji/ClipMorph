/**
 * Control-kind + option metadata for the generated configuration form
 * (issue #259 D6/D7). Pure data: no store or component imports, so the
 * mapping is unit-testable and the Svelte renderer stays a plain template.
 */

/** Free-text fields the forms keep (D7): content title, description, tags. */
export const FREE_TEXT_PATHS = new Set([
  'upload.content.title',
  'upload.content.description',
  'upload.content.tags',
]);

/**
 * Dropdown tables for the enumerated fields the spec types as plain strings
 * (D7). Human-readable labels never change the stored value, so raw enum keys
 * stay out of the UI (U15's value handling applies inside the spec's own
 * enum fields as well). Keys are path leaves; every platform shares values
 * where the platform APIs agree.
 */
export const STATIC_OPTION_LEAVES = {
  // faster-whisper / WhisperX model sizes and runtime targets.
  transcription_model: ['tiny', 'base', 'small', 'medium', 'large-v3'].map((value) => ({
    value,
    label: value,
  })),
  transcription_device: ['auto', 'cpu', 'cuda', 'mps'].map((value) => ({
    value,
    label: value,
  })),
  transcription_compute_type: ['int8', 'int8_float16', 'float16', 'float32'].map(
    (value) => ({ value, label: value }),
  ),
  // YouTube privacy + the official public video category ids.
  privacy_status: [
    { value: 'public', label: 'Public' },
    { value: 'private', label: 'Private' },
    { value: 'unlisted', label: 'Unlisted' },
  ],
  category: [
    { value: '1', label: 'Film & Animation' },
    { value: '2', label: 'Autos & Vehicles' },
    { value: '10', label: 'Music' },
    { value: '15', label: 'Pets & Animals' },
    { value: '17', label: 'Sports' },
    { value: '19', label: 'Travel & Events' },
    { value: '20', label: 'Gaming' },
    { value: '22', label: 'People & Blogs' },
    { value: '23', label: 'Comedy' },
    { value: '24', label: 'Entertainment' },
    { value: '25', label: 'News & Politics' },
    { value: '26', label: 'Howto & Style' },
    { value: '27', label: 'Education' },
    { value: '28', label: 'Science & Technology' },
  ],
  // TikTok privacy levels.
  privacy_level: [
    { value: 'PUBLIC_TO_EVERYONE', label: 'Public to everyone' },
    { value: 'MUTUAL_FOLLOW_FRIENDS', label: 'Mutual follow friends' },
    { value: 'SELF_ONLY', label: 'Self only' },
  ],
  // Facebook content kind (same option family as the publish form).
  content_kind: [
    { value: 'reel', label: 'Reel' },
    { value: 'video', label: 'Page video' },
  ],
};

/** Title-case an underscore-joined enum key for its dropdown label (U15). */
export function enumLabel(value) {
  const words = String(value ?? '').replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function staticOptions(field) {
  const record = STATIC_OPTION_LEAVES[field.path.split('.').pop()];
  return record ? [...record] : null;
}

/**
 * The control a field renders as (D6 associations happen in ConfigForm):
 * ``hidden`` fields (the free-form inline-layout object) are dropped entirely
 * (D7: inline layout overrides belong to the Layouts editor); ``select`` is
 * every enumerated field; free text survives only for title/description/tags.
 */
export function controlDescriptor(field, layouts = []) {
  if (field.type === 'object') return { kind: 'hidden', options: [] };
  if (field.type === 'enum') {
    return {
      kind: 'select',
      options: (field.options || []).map((value) => ({ value, label: enumLabel(value) })),
    };
  }
  if (field.path === 'conversion.layout_id') {
    return {
      kind: 'select',
      options: (layouts || []).map((layout) => ({ value: layout.id, label: layout.name })),
    };
  }
  const options = staticOptions(field);
  if (options) return { kind: 'select', options };
  switch (field.type) {
    case 'boolean':
      return { kind: 'checkbox', options: [] };
    case 'datetime':
      return { kind: 'datetime', options: [] };
    case 'text':
      return { kind: 'textarea', options: [] };
    case 'string_list':
      return { kind: 'string_list', options: [] };
    case 'integer':
    case 'number':
      return { kind: 'number', options: [] };
    default:
      return { kind: 'text', options: [] };
  }
}
