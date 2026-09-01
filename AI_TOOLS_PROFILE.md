# AI Tools Content Profile Guide

## Overview

The `ai_tools` content profile enables ContentPoster to generate educational, informative reels about AI and machine learning concepts. It creates high-quality infographic-style visual explanations with readable titles and detailed captions.

## Features

### Visual Style
- **Professional infographic design** with clean typography
- **Readable text elements** integrated into generated images
- **Color-coded information flows** showing system interactions
- **Technical diagrams** with clear visual hierarchy
- **Educational composition** emphasizing clarity and accuracy
- **Modern aesthetic** with scientific authority

### Content Coverage

The profile supports 12 key AI/ML concepts as primary topics:

1. **RAG Architecture** - Retrieval-Augmented Generation systems
   - Vector databases, query processing, response generation
   - Data flow visualization

2. **In-Context Learning** - Learning from examples within context
   - Context window visualization
   - Attention mechanism emphasis
   - Prompt to output flow

3. **Transformer Architecture** - Neural network foundations
   - Multi-head attention visualization
   - Feed-forward networks
   - Layer-by-layer processing

4. **Token Embedding Space** - High-dimensional representations
   - 3D-style visualization of embeddings
   - Semantic relationships and clusters
   - Proximity-based concept grouping

5. **Fine-tuning Process** - Model adaptation and training
   - Dataset preparation stages
   - Training loop visualization
   - Model refinement steps

6. **Prompt Engineering Flow** - Optimization workflows
   - Iteration process visualization
   - Template structuring
   - Quality metrics display

7. **Multimodal AI System** - Cross-modal processing
   - Text, image, audio integration
   - Unified embedding space
   - Cross-modal connections

8. **Knowledge Graph Integration** - Structured knowledge
   - Entity-relationship networks
   - Knowledge retrieval visualization
   - Reasoning enhancement

9. **Chain-of-Thought Reasoning** - Step-by-step logic
   - Multi-hop reasoning paths
   - Intermediate conclusions
   - Logical flow visualization

10. **Loss Landscape Visualization** - Training optimization
    - 3D terrain metaphor
    - Convergence paths
    - Optimization trajectory

11. **Attention Mechanism** - Token relationships
    - Weight visualization
    - Focus pattern heatmaps
    - Relationship strength indicators

12. **Model Scaling Laws** - Performance trends
    - Size vs. performance relationships
    - Compute scaling graphs
    - Predictive trajectories

## Activation

### Method 1: Environment Variable
```bash
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools
```

### Method 2: Configuration File
Edit `config/config.yaml`:
```yaml
content:
  active_profile: "ai_tools"
```

### Method 3: Command Line (if supported)
```bash
autogram run --content-profile ai_tools
```

## Caption Strategy

The profile is optimized for **long, detailed captions**. Recommendations:

### Caption Length
- Set appropriate length limits in `config/config.yaml`:
  ```yaml
  caption:
    max_length: 2200  # Can be increased for more detailed explanations
  ```

### Caption Tone
Configure the caption style:
```yaml
caption:
  tone: "educational, technical, authoritative, accessible"
```

### Caption Structure
The generated captions will include:
1. **Hook** - Compelling opening about the concept
2. **Explanation** - Clear, detailed breakdown of the mechanism
3. **Application** - Real-world use cases and importance
4. **Technical Details** - Relevant parameters and considerations
5. **Resources** - References to papers or learning materials

### Hashtag Configuration
For educational content, optimize hashtag strategy:
```yaml
hashtags:
  tier_broad: 0.30    # Popular #ArtificialIntelligence #MachineLearning
  tier_mid: 0.50      # Mid-tier #TransformerArchitecture #LLMs
  tier_niche: 0.20    # Niche #RAG #PromptEngineering
  min_count: 8
  max_count: 20
```

## Visual Generation Tips

### Image Settings
For best results with technical diagrams:
```yaml
image:
  steps: 25-30         # Higher for clarity (default 20)
  guidance_scale: 6.5  # Standard
  model: "Lykon/dreamshaper-8"  # For CPU
  hq_model: "black-forest-labs/FLUX.1-schnell"  # For GPU
```

### Composition Recommendations
The profile includes these composition styles:
- Centered symmetrical (core concept emphasis)
- Rule-of-thirds (technical element placement)
- Layered (system components at different depths)
- Flow-based (data pathway direction)
- Gridded (organized information)
- Diagonal (transformation/progression)
- Concentric (concept surrounded by related ideas)
- Split-screen (comparisons)

### Color Palette Options
The profile uses multiple color schemes:
- **Tech Blue**: Professional blues, teals, purples with white
- **Minimalist**: Monochromatic with strategic accents
- **Data Viz**: Complementary colors for contrast
- **Gradient**: Smooth transitions showing relationships
- **Neon Accent**: Bright technical elements for engagement

## Content Generation Workflow

### Step 1: Activate Profile
```bash
export AUTOGRAM_CONTENT__ACTIVE_PROFILE=ai_tools
```

### Step 2: Run Generation
```bash
autogram run
```

### Step 3: Review Output
- Check `out/` directory for generated content
- Review caption quality and technical accuracy
- Verify visual hierarchy and readability

### Step 4: Post to Instagram/YouTube
Use the poster backends to publish:
```bash
autogram post --platform instagram
```

## Customization

### Adding New AI Concepts

To add a new concept, edit `config/config.yaml` under `ai_tools > visual > locations > ai_concepts`:

```yaml
- name: "Your AI Concept"
  description: >
    visual diagram showing [your concept] with [key elements]
    connected by [relationship type]
  lighting: >
    [lighting style appropriate for the concept]
  mood: >
    [emotional/educational tone]
```

### Adjusting Visual Style

Modify interaction styles:
```yaml
interaction_styles:
  - "your custom visual explanation style"
  - "another visual approach"
```

### Tweaking Design Elements

Customize in `visual_elements` section:
- Typography styles
- Color coding schemes
- Diagram types
- Icon systems
- Annotation styles

## Best Practices

### 1. Caption Writing
- Start with a compelling hook about the importance of the concept
- Explain the mechanism in accessible language
- Include specific examples and use cases
- Reference research papers or key figures when relevant
- Keep technical accuracy while remaining understandable

### 2. Visual Clarity
- Ensure text in images is readable (18pt+ minimum)
- Use consistent color coding across multiple posts
- Organize complex information hierarchically
- Include legends and labels for all visual elements
- Test readability on mobile devices

### 3. Concept Selection
- Prioritize concepts with visual explanations
- Mix foundational topics with cutting-edge research
- Sequence concepts from basic to advanced
- Connect related concepts across posts
- Highlight real-world applications

### 4. Engagement Strategy
- Use captions to build understanding progressively
- Include discussion prompts in comments
- Reference other posts in the same series
- Share in educational AI communities
- Cross-link related concepts

## Quality Assurance

### Image Quality Checks
- [ ] Title text is clearly readable
- [ ] Diagram elements are properly labeled
- [ ] Color coding is consistent and meaningful
- [ ] Visual hierarchy guides attention correctly
- [ ] Technical accuracy is maintained
- [ ] Resolution is appropriate for platform

### Caption Quality Checks
- [ ] Hook is compelling and relevant
- [ ] Explanation is clear and accurate
- [ ] Examples illustrate the concept
- [ ] Technical terms are properly defined
- [ ] Length is appropriate (not too long/short)
- [ ] Hashtags are relevant and tiered

## Troubleshooting

### Issue: Generated images don't match topic
**Solution**: Increase `image.steps` for better quality, or adjust `guidance_scale` for better prompt adherence.

### Issue: Text in images is blurry
**Solution**: Increase image resolution or use the HQ model (requires GPU).

### Issue: Technical inaccuracy in caption
**Solution**: Adjust the `hq_model` setting to use a more capable LLM, or manually refine captions.

### Issue: Caption is too long/short
**Solution**: Adjust `caption.max_length` in config.yaml to match platform requirements.

## Integration with Accounts System

To use ai_tools with specific Instagram/YouTube accounts:

```yaml
accounts:
  - id: ai_education
    platform: instagram
    backend: instagrapi
    profile: ai_tools
    enabled: true
    content_mix:
      reel: 4
      carousel: 1
      photo: 0
    audio_dir: "assets/audio"
```

## Performance Notes

- **CPU Generation**: ~3-5 minutes per reel with 20 steps
- **GPU Generation**: ~1-2 minutes per reel with HQ settings
- **Caption Generation**: ~30-60 seconds with Ollama
- **Total Time**: 5-10 minutes per reel (CPU) or 2-4 minutes (GPU)

## Future Enhancements

Planned improvements for the ai_tools profile:
- [ ] Pre-built concept templates for specific topics
- [ ] Interactive diagram generation
- [ ] Animation support for concept visualization
- [ ] Citation and reference overlay system
- [ ] Multi-language caption support
- [ ] Citation linking to papers and resources

## Support & Resources

- **Configuration Help**: See CONFIGURE.md
- **Full Documentation**: See README.md
- **Example Workflows**: See QUICKSTART.md
- **AI Concepts**: Check research papers in the community

---

**Profile Version**: 1.0  
**Last Updated**: 2024  
**Status**: Production Ready
