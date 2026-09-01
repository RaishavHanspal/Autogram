# AI Tools Profile - Quick Start Examples

## Example 1: Basic Profile Activation

### Step 1: Update config.yaml
```yaml
content:
  active_profile: "ai_tools"
```

### Step 2: Run Content Generation
```bash
cd ContentPoster
python -m autogram run
```

### Expected Output
- Generated reel with AI concept visualization
- High-quality infographic-style image
- Long, detailed educational caption
- Relevant hashtags (AI, ML, Education)

---

## Example 2: Generate Specific AI Concept Content

### Using Environment Variables
```bash
# Override profile via environment
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools

# Run the generation
python -m autogram run
```

### Output Examples

#### RAG Architecture Concept
**Visual**: Diagram showing retrieval flow from user query → vector database → context retrieval → model generation

**Caption Preview**:
```
How does Retrieval-Augmented Generation work? Let me break it down...

RAG combines the strengths of two approaches: retrieval-based systems 
and generative models. When you ask a question, the system first searches 
a knowledge base (vector database) to find relevant documents or passages. 
These are then fed as context to a language model, which generates a 
response grounded in actual information rather than its training data alone.

This approach significantly improves:
• Accuracy - Responses are based on retrieved facts
• Freshness - Can include recent documents
• Verifiability - You can trace where information came from
• Reduced Hallucination - Facts limit creative fabrication

Perfect for Q&A systems, documentation assistants, and knowledge-based chatbots.
```

#### Transformer Architecture Concept
**Visual**: Layered diagram showing attention heads, feed-forward networks, and token processing

**Caption Preview**:
```
Inside the Transformer: The Architecture Powering Modern AI

The Transformer architecture, introduced in 2017, revolutionized deep learning 
through the attention mechanism. Instead of processing sequences linearly, 
transformers compute relationships between ALL tokens simultaneously.

Core Components:

1. Multi-Head Attention: Multiple "attention heads" focus on different aspects
   of the input. Some heads might track pronouns, others track actions.

2. Feed-Forward Networks: After attention, each token passes through 
   fully-connected layers that apply non-linear transformations.

3. Layer Normalization: Stabilizes training by normalizing activations.

4. Positional Encoding: Since transformers lack sequential structure, position 
   information is explicitly added.

Key Innovation: Unlike RNNs, transformers process the entire sequence in 
parallel, enabling efficient training on massive datasets. This parallel 
processing is why GPT and BERT can handle such large scale!
```

#### In-Context Learning Concept
**Visual**: Flowchart showing prompt with examples → context window → model processing → output generation

**Caption Preview**:
```
In-Context Learning: How LLMs Learn Without Training

In-context learning is the remarkable ability of large language models to 
learn from examples provided directly in the prompt, without any weight updates 
or fine-tuning. It's one of the most surprising emergent capabilities of scale.

How it works:

The model receives:
• Task description (what you want)
• Few examples (2-5 demonstrations)
• The actual problem to solve

The model's attention mechanism learns to identify the pattern from examples 
and applies it to your actual query. It's like showing someone how to do 
something 3 times, then they do it on their own.

This enables:
✓ Zero-shot learning (no examples needed)
✓ Few-shot learning (2-5 examples suffice)
✓ Novel task adaptation without fine-tuning
✓ Rapid experimentation

The more capable the model and the more parameters it has, the better 
in-context learning performs!
```

---

## Example 3: Content Mix Configuration

For multi-profile account setup:

```yaml
accounts:
  - id: ai_education
    platform: instagram
    backend: instagrapi
    profile: ai_tools
    enabled: true
    content_mix:
      reel: 80      # Mostly reels for educational content
      carousel: 15  # Occasional comparison carousels
      photo: 5      # Rare single-image posts
    audio_dir: "assets/audio"
```

---

## Example 4: Optimized Caption Settings

For detailed educational captions:

```yaml
caption:
  # Allow longer captions for detailed explanations
  max_length: 2200
  
  tone: "educational, technical, authoritative, accessible"
  
  emoji_budget: 3
  
  hashtag_placement: "caption"  # Place hashtags in caption, not comments

hashtags:
  min_count: 10
  max_count: 20
  
  # Distribution for educational AI content
  tier_broad: 0.30      # #AI #MachineLearning #DeepLearning
  tier_mid: 0.50        # #Transformers #LLMs #NeuralNetworks
  tier_niche: 0.20      # #RAG #InContextLearning #PromptEngineering
  
  # Brand/channel tags
  brand_tags:
    - "#AIEducation"
    - "#MLExplained"
    - "#TechLearning"
```

---

## Example 5: Multi-Concept Campaign

Running a week-long educational campaign:

```bash
# Day 1: RAG Architecture
# Day 2: In-Context Learning
# Day 3: Transformer Architecture
# Day 4: Attention Mechanism
# Day 5: Fine-tuning Process
# Day 6: Multimodal AI
# Day 7: Recap with scaling laws

# Each day:
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools
python -m autogram run --post
```

This creates a cohesive educational series that builds understanding progressively.

---

## Example 6: High-Quality GPU Generation

For highest quality output with detailed technical accuracy:

```yaml
image:
  # Use HQ model when GPU available
  hq_model: "black-forest-labs/FLUX.1-schnell"
  
  # More steps for detail
  hq_steps: 6
  hq_guidance_scale: 0.0

llm:
  # Use more capable LLM for captions
  model: "qwen2.5:7b-instruct"  # More capable than 3b
```

---

## Example 7: Concept-Specific Customization

Adding custom AI concept to the profile:

```yaml
ai_tools:
  visual:
    locations:
      ai_concepts:
        # Add after existing concepts
        - name: "Emergent Abilities"
          description: >
            visualization showing how certain capabilities suddenly appear
            at scale thresholds, with performance curves showing phase transitions
          lighting: >
            scientific lighting with emphasis on transition points
          mood: >
            surprising, revealing, breakthrough moment
```

---

## Example 8: Performance Optimization

For running on CPU hardware:

```yaml
image:
  # Reduce for speed on CPU
  steps: 18
  model: "Lykon/dreamshaper-8"

llm:
  # Use smaller model
  model: "qwen2.5:3b-instruct"
  # Reduce retries
  max_retries: 2
  
  # Reduce request timeout
  request_timeout_s: 90
```

**Expected performance**: ~4-6 minutes per reel on CPU

---

## Example 9: Instagram Reel Dimensions

The profile generates optimal dimensions for Instagram:

```yaml
postproc:
  aspect: "4:5"  # Optimal for Instagram Reels

# Output dimensions: 1080x1350 pixels
# Perfect for vertical video on mobile
```

---

## Example 10: State & History

The profile maintains history to avoid duplicate concepts:

```yaml
brief:
  history_depth: 30  # Remember last 30 concepts generated
  dedupe_threshold: 85  # Don't repeat similar concepts
```

This ensures variety in your educational content series.

---

## Testing the Setup

### 1. Validate Configuration
```bash
cd ContentPoster
python -c "from autogram.config import Config; cfg = Config.load('config/config.yaml'); print(list(cfg.content.profiles.keys()))"
```

Should output: `['romance', 'ai_tools']`

### 2. Test Profile Loading
```bash
python -c "
from autogram.config import Config
cfg = Config.load('config/config.yaml')
cfg.content.active_profile = 'ai_tools'
print('Profile:', cfg.content.active.theme[:100])
"
```

### 3. Run Dry-Run Generation
```bash
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools
python -m autogram run --image-only  # Generate image only, no posting
```

---

## Common Generation Patterns

### Pattern 1: Daily AI Concept Series
```bash
#!/bin/bash
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools

for i in {1..7}; do
  python -m autogram run --post
  sleep 3600  # Wait 1 hour between posts
done
```

### Pattern 2: Batch Generation
```bash
#!/bin/bash
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools

for i in {1..10}; do
  python -m autogram run  # Generate but don't post
done

# Then review and post manually
```

### Pattern 3: Scheduled Generation
```bash
# In crontab:
0 9 * * * cd /path/to/ContentPoster && \
          export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools && \
          python -m autogram run --post
```

---

## Next Steps

1. **Activate the profile** in your config.yaml
2. **Test generation** with `--image-only` flag
3. **Review output** for quality and accuracy
4. **Customize captions** based on your audience
5. **Schedule posts** for consistent educational content
6. **Monitor engagement** and refine based on metrics

For detailed configuration options, see [AI_TOOLS_PROFILE.md](AI_TOOLS_PROFILE.md)
