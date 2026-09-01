# AI Tools Profile - Technical Documentation

## Profile Architecture

### Configuration Structure

The `ai_tools` profile is defined in `config/config.yaml` under:
```yaml
content:
  profiles:
    ai_tools:
      theme: "..."
      system_prompt: "..."
      subject_instruction: "..."
      prompt_anchor: "..."
      visual: {...}
```

### Key Components

#### 1. Theme
The high-level creative direction for all AI tools content:
- **Purpose**: Sets the overall aesthetic and educational tone
- **Used by**: Image generation LLM (indirect), prompt construction
- **Format**: Multi-line string describing visual style

#### 2. System Prompt
Instructions for the brief generation LLM:
- **Purpose**: Guides scene generation and brief construction
- **Used by**: Ollama LLM during brief generation phase
- **Format**: Detailed instructions emphasizing educational clarity

#### 3. Subject Instruction
Specific guidance for the main scene concept:
- **Purpose**: Ensures each generated image explains a clear AI concept
- **Used by**: Brief generation to create the core scene narrative
- **Format**: Specific requirements for visual communication

#### 4. Prompt Anchor
Consistent visual identity for the profile:
- **Purpose**: Keeps generated images coherent and recognizable
- **Used by**: Image prompt rendering, CLIP token allocation
- **Format**: Short, impactful descriptor (kept brief for CLIP efficiency)

#### 5. Visual Section
Detailed creative vocabulary and options:
```yaml
visual:
  interaction_styles: [...]    # How concepts are shown
  moods_and_emotions: [...]    # Emotional tone
  locations:                   # Content/concept definitions
    ai_concepts: [...]
  photography_trends:
    compositions: [...]
    lighting_styles: [...]
    color_grading: [...]
    depth_of_field: [...]
  visual_elements: [...]       # Design components
  technical_accuracy_elements: [...]
```

## Generation Pipeline

### Step 1: Brief Generation
```
Config (ai_tools profile)
    ↓
Ollama LLM (with system_prompt + subject_instruction)
    ↓
Random selection of:
  - AI concept from locations.ai_concepts
  - interaction_style from interaction_styles
  - mood from moods_and_emotions
  - camera angles, focal lengths, etc. from brief.axes
    ↓
Brief object (contains scene description)
```

**Key Logic in `autogram/scene.py`:**
```python
# Select one AI concept location
location = select_unique_location(rng, all_locations, history_locations)

# Get creative axes
axis_hints = select_axis_hints(rng, cfg.brief.axes)

# Build LLM prompt with all context
messages = _build_messages(
    cfg,
    axis_hints,
    recent_briefs,
    error_feedback,
    characters_data,  # From visual section
    selected_location,  # The AI concept
    style  # Selected from visual elements
)

# Generate brief
brief = ollama_client.chat_json(messages)
```

### Step 2: Prompt Rendering
```
Brief object + AI Tools profile config
    ↓
render_prompts() function
    ↓
Positive Prompt:
  [prompt_anchor]
  [theme concepts]
  [brief components]
  [interaction style]
  [mood/emotion]
  [composition style]
  [lighting style]
  [color palette]
  [visual elements]
    ↓
Negative Prompt:
  [generic negative terms]
```

**Example Rendered Prompt:**
```
professional educational infographic, technical diagram, clean modern design, 
readable sans-serif typography, scientific accuracy, high-quality educational 
infographic-style visual explanations of artificial intelligence concepts, 
Retrieval-Augmented Generation architecture with vector database showing 
query flow and context retrieval, visual diagram showing information flow 
with color-coded arrows, clear visual explanation with data flowing from 
left to right, systematic and technically sophisticated mood, rule-of-thirds 
composition, professional tech palette with blues and teals, sharp focus 
throughout for maximum technical clarity
```

### Step 3: Image Generation
```
Positive & Negative Prompts
    ↓
Diffusers Pipeline (DreamShaper 8 or FLUX.1-schnell)
    ↓
Generated PIL Image
    ↓
Post-processing (aspect ratio, color correction, unsharp mask)
    ↓
Final JPEG/PNG
```

### Step 4: Caption Generation
```
Brief object
    ↓
Ollama LLM (different prompt for captions)
    ↓
Generate caption + hashtags + alt_text
    ↓
Apply safety gates
    ↓
Hashtag processing (tier distribution, banned word filter)
    ↓
Final caption string
```

## Customization Guide

### Adding New AI Concepts

**Location:** `config/config.yaml` → `content.profiles.ai_tools.visual.locations.ai_concepts`

**Structure:**
```yaml
- name: "Concept Name"                    # Unique identifier
  description: >                          # What to visualize
    visual diagram showing [key elements]
    with [relationships] connected by
    [visual metaphor]
  lighting: >                            # Lighting for this concept
    [appropriate technical lighting style]
  mood: >                                # Emotional/educational tone
    [specific mood descriptors]
```

**Guidelines:**
- **Name**: 2-4 words, specific and searchable
- **Description**: 2-3 sentences describing visual representation
- **Lighting**: Use "technical", "clean", "professional", "scientific"
- **Mood**: Educational but varied (systematic, inspiring, practical, etc.)

**Example Addition:**
```yaml
- name: "Gradient Descent Optimization"
  description: >
    3D landscape visualization showing loss function surface with 
    optimization trajectory spiraling downward toward minimum valley, 
    gradient vectors pointing toward lower regions
  lighting: >
    gradient technical lighting showing elevation and direction
  mood: >
    systematic, directional, and methodically progressive
```

### Adding New Visual Styles

**Interaction Styles:**
Location: `visual.interaction_styles`

```yaml
interaction_styles:
  - "new way of showing information"
  - "alternative visual communication method"
```

**Moods:**
Location: `visual.moods_and_emotions`

```yaml
moods_and_emotions:
  - "new emotional tone for content"
  - "alternative mood/feeling"
```

**Compositions:**
Location: `visual.photography_trends.compositions`

```yaml
compositions:
  - "new compositional arrangement"
  - "alternative layout approach"
```

**Lighting Styles:**
Location: `visual.photography_trends.lighting_styles`

```yaml
lighting_styles:
  - "new lighting approach"
  - "alternative illumination style"
```

**Color Grading:**
Location: `visual.photography_trends.color_grading`

```yaml
color_grading:
  - "new color palette or scheme"
  - "alternative color treatment"
```

### Creating Profile Variants

**Example: ai_tools_advanced** (for research-focused content)

```yaml
ai_tools_advanced:
  theme: "advanced research-grade technical visualization..."
  system_prompt: "You are generating content for ML researchers..."
  subject_instruction: "Create advanced technical explanations..."
  prompt_anchor: "peer-reviewed research poster, academic visualization..."
  visual:
    interaction_styles:
      - "mathematical derivation visualization"
      - "algorithm pseudocode display"
      - "empirical results graphs"
    # ... rest of visual config
```

## Integration Points

### 1. Brief Generation (`autogram/scene.py`)
- **File**: `autogram/scene.py`
- **Function**: `generate_brief()`
- **How ai_tools used**: 
  - Selects from `visual.locations.ai_concepts`
  - Uses `system_prompt` for LLM instructions
  - Selects from `visual.interaction_styles`, moods, etc.

### 2. Prompt Rendering (`autogram/scene.py`)
- **File**: `autogram/scene.py`
- **Functions**: `_render_compact_positive()`, `_render_template_positive()`
- **How ai_tools used**:
  - Includes `theme` in prompt
  - Uses `prompt_anchor` at beginning
  - Incorporates visual elements into final prompt

### 3. Image Generation (`autogram/imagegen.py`)
- **File**: `autogram/imagegen.py`
- **Class**: `ImageGenerator`
- **How ai_tools used**:
  - Receives complete prompt string
  - Generates image based on prompt
  - No direct knowledge of profile

### 4. Caption Generation (`autogram/caption.py`)
- **File**: `autogram/caption.py`
- **Function**: `generate_caption()`
- **How ai_tools used**:
  - Receives `Brief` object with AI concept data
  - Generates educational caption
  - No direct knowledge of profile (uses Brief structure)

### 5. Content Types (`autogram/content/`)
- **Reel** (`reel.py`): Uses profile for multi-scene generation
- **Photo** (`photo.py`): Uses profile for single-image content
- **Carousel** (`carousel.py`): Uses profile for multi-slide albums

## Data Flow Example

### For a RAG Architecture Reel

```
1. Config Loading
   ├─ Reads ai_tools profile
   ├─ Loads ai_concepts locations
   └─ Prepares visual vocabulary

2. Brief Generation (Scene 1)
   ├─ Selects: "RAG Architecture" location
   ├─ Selects: "clear visual explanation with data flowing..." style
   ├─ Selects: "systematic, organized..." mood
   ├─ Assembles LLM prompt with all context
   ├─ Ollama generates: {subject, setting, lighting, mood, composition}
   └─ Creates: Brief(subject="RAG system with...", mood="systematic...")

3. Prompt Rendering
   ├─ Starts with prompt_anchor: "professional educational infographic..."
   ├─ Adds theme: "high-quality educational infographic-style..."
   ├─ Adds brief components: all Brief fields
   ├─ Adds visual context: interaction style, mood, composition, lighting
   └─ Final: "professional educational infographic... RAG Architecture..."

4. Image Generation
   ├─ DreamShaper pipeline receives full prompt
   ├─ Generates 512x512 image
   └─ Produces infographic-style RAG diagram

5. Post-Processing
   ├─ Crops to 1080x1350 (4:5 aspect)
   ├─ Color correction
   └─ Unsharp mask for clarity

6. Caption Generation
   ├─ Ollama receives Brief with RAG subject
   ├─ Generates educational explanation
   ├─ Adds hashtags: #RAG #LLM #AI #MachineLearning
   └─ Final caption: "How does RAG work? Let me explain..."

7. Deliverable
   ├─ Media: reel.mp4 (with optional AI motion)
   ├─ Caption: educational text with hashtags
   ├─ Alt text: accessibility description
   └─ Hashtags: [list of tags]
```

## Performance Characteristics

### CPU Execution (Typical)
- Brief Generation: 15-30 seconds (Ollama 3B)
- Image Generation: 60-90 seconds (DreamShaper, 20 steps)
- Post-processing: 2-5 seconds
- Caption Generation: 30-60 seconds (Ollama 3B)
- **Total per reel**: 2-4 minutes

### GPU Execution (With CUDA)
- Brief Generation: 5-10 seconds (Ollama 7B)
- Image Generation: 10-15 seconds (FLUX.1-schnell, 4-6 steps)
- Post-processing: 1-2 seconds
- Caption Generation: 10-20 seconds (Ollama 7B)
- **Total per reel**: 30-60 seconds

## Extending the Profile

### Option 1: Add to Existing Profile
```yaml
ai_tools:
  visual:
    locations:
      ai_concepts:
        - # Add new concept here
```

### Option 2: Create Related Profile
```yaml
ai_tools_research:
  theme: "..."
  # Different emphasis
  
ai_tools_beginner:
  theme: "..."
  # Simplified explanations
```

### Option 3: Create Profile Category
```yaml
science:
  profiles:
    ai_tools:
      # AI/ML specific
    physics:
      # Physics concepts
    biology:
      # Biology concepts
```

## Testing & Validation

### 1. Configuration Validation
```python
from autogram.config import Config
cfg = Config.load('config/config.yaml')
assert 'ai_tools' in cfg.content.profiles
assert cfg.content.profiles['ai_tools'].visual
```

### 2. Brief Generation Test
```python
from autogram.scene import generate_brief
brief = generate_brief(ollama_client, cfg, seed, run_date, [], [])
assert brief.subject  # Should have concept
assert brief.mood      # Should have mood
```

### 3. Prompt Rendering Test
```python
from autogram.scene import render_prompts
positive, negative = render_prompts(brief, cfg)
assert 'educational' in positive.lower()
assert 'infographic' in positive.lower()
```

### 4. Full Content Generation Test
```python
from autogram.content.reel import Reel
reel_producer = Reel()
deliverable = reel_producer.produce(ctx)
assert deliverable.media  # Has video/image
assert deliverable.caption  # Has caption
```

## Debugging

### Enable Debug Logging
```bash
export AUTOGRAM_LOG_LEVEL=DEBUG
python -m autogram run
```

### Common Issues

**Issue: Images don't show AI concept**
- Check: prompt_anchor is specific enough
- Increase: image.guidance_scale (6.5 → 7.5)
- Add: more descriptive interaction style

**Issue: Captions mention wrong concept**
- Check: Brief.subject is correctly populated
- Review: Ollama model outputs (check logs)
- Increase: llm.temperature (varies output)

**Issue: Visual style doesn't match profile**
- Check: All visual elements are in config
- Verify: Brief includes correct mood/composition
- Increase: image.steps for more detailed rendering

## Related Documentation

- [AI_TOOLS_PROFILE.md](AI_TOOLS_PROFILE.md) - User guide
- [AI_TOOLS_EXAMPLES.md](AI_TOOLS_EXAMPLES.md) - Usage examples
- [CONFIGURE.md](CONFIGURE.md) - Full configuration reference
- [README.md](README.md) - Project overview

---

**Technical Documentation Version**: 1.0  
**Last Updated**: 2024  
**Profile**: ai_tools v1.0
