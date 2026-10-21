/*
 * Keep flame's command-mode panel refreshing from the splash buffer.
 * Addresses from sm8150-sde.dtsi and sde_hw_{ctl,pingpong}.c of Google's
 * android-msm-coral-4.14 kernel. Mainline drives flame with a plain
 * simple-framebuffer on this buffer, which suggests ABL leaves autorefresh
 * running; this only steps in when it finds it off.
 *
 * Build with -DFLAME_MDP_KICK=0 to only read the registers.
 */
#include "mdp.h"

#ifndef FLAME_MDP_KICK
#define FLAME_MDP_KICK		1
#endif

#define MDP_CTL0		0x0ae02000UL
#define CTL_FLUSH		0x18
#define CTL_START		0x1c
#define MDP_PP0			0x0ae71000UL
#define MDP_PP1			0x0ae71800UL
#define PP_AUTOREFRESH_CONFIG	0x30
#define AUTOREFRESH_EN		(1U << 31)

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

void mdp_autorefresh(struct mdp_state *st)
{
	st->pp0 = rd32(MDP_PP0 + PP_AUTOREFRESH_CONFIG);
	st->pp1 = rd32(MDP_PP1 + PP_AUTOREFRESH_CONFIG);
	st->ctl0_flush = rd32(MDP_CTL0 + CTL_FLUSH);
	st->kicked = 0;
	if ((st->pp0 | st->pp1) & AUTOREFRESH_EN)
		return;
#if FLAME_MDP_KICK
	/*
	 * Refetch every TE (frame count 1), then one CTL start to arm it.
	 * Upstream DPU warns against CTL_START while autorefresh already
	 * runs, hence the check above.
	 */
	wr32(MDP_PP0 + PP_AUTOREFRESH_CONFIG, AUTOREFRESH_EN | 1);
	__asm__ volatile("dsb sy" ::: "memory");
	wr32(MDP_CTL0 + CTL_START, 1);
	__asm__ volatile("dsb sy" ::: "memory");
	st->kicked = 1;
#endif
}
