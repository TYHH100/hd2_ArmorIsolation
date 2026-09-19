#pragma once
#include <cstddef>
#include <cstdint>

namespace cm14_isolation {
inline constexpr char expected_game_dll_sha256[] = "cc75948d90fdfde259dcb519e9933db7ffa3ccb281ce4fb89e6b1b011557470c";
inline constexpr char expected_game_version[] = "1.0.0.18930";
inline constexpr char source_main_sha256[] = "c31a0983d6779df0891dab1766a2ebb04063117cdfbf9bf94d47d7fd781d4450";
struct ResourceMapping { std::uint32_t kit_id; std::uint64_t type, source, target; };
inline constexpr ResourceMapping resources[] = {
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0x2127dc72b6eb25ebULL, 0x38c717385b99166cULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0x5e76170332d7cd0aULL, 0x79435e6ca02f2cb0ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0x7ed6627f592fec43ULL, 0xfabe81d570e1556aULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0x8bd8b90e25579a06ULL, 0xae9824ed641dae50ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xa29c66bf361dd379ULL, 0x308d1cfeca037dd1ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xa4ba0587e085ae48ULL, 0xcaa06fc5d27fd038ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xc6596d4faf05d12cULL, 0x9cbe84c4a4fdd5ffULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xd5879965d92e80daULL, 0x776556ec99277058ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xe702eab54ef3c6ecULL, 0x179c925bda6378d2ULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xf446860551e18f8fULL, 0xabab40a640b97ffdULL},
    {0x38aa207dU, 0xcd4238c6a0c69e32ULL, 0xf6ed26225df0d01dULL, 0xaf2f4768abc060feULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x01144a44b65471bdULL, 0x7cb30f2385f5dfc1ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x0387a158d04848f4ULL, 0x72acc94806914431ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x0fbf63f07f72cd4dULL, 0xace03dcb9bb28b8eULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x1a9053f944788708ULL, 0x93741a38c38e353aULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x1c058e9048d4966cULL, 0xbfc7c5e5b6072ac0ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x1faef78c66ec2ed1ULL, 0x84259e9cf1dfce15ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x29099ce94f27b208ULL, 0xfa3fe275555f500eULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x2f66b9373cb58485ULL, 0xe959e2ea146868ceULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x3e43b08cfa451e44ULL, 0x1569aadfe9bb74e7ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x44f53e9787ca3ffcULL, 0xe74562cfc94ed2b3ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x55dea3c1dcac7841ULL, 0x6d36cac55535566bULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x593a2a0d7099aef8ULL, 0xef78c166e3cc6760ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x6612fc2ac51c20d1ULL, 0xd5a879ed1bbd7884ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x79740c9dbb23a2d8ULL, 0xfc78a4dc5a5352d5ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x7a3dbeaecacba925ULL, 0x3f44e84458510237ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x7cbc9209d9736a6bULL, 0x6234440435142775ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x803419f30e7b8f16ULL, 0xd9ed0d1a042320e1ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x8d857a8a57a8874bULL, 0x8b99bb6354161787ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x8df62e0fbe3864c7ULL, 0xed56aa60d9f1c06fULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0x9ef5adcfb96fdc57ULL, 0x8e99b9627cb6cf2dULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xa2a205819f79ee41ULL, 0xd49425d58df0409aULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xbc5b49605ab674d7ULL, 0x3d3c9fd7a5b5ed0eULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xc7e47f2d8d5f8b40ULL, 0x059c1d6e991e6644ULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xd2b77c8e346f2fdbULL, 0xe45e9e71944e857bULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xf7f232ee26ec35fbULL, 0x50d197735c64454eULL},
    {0x38aa207dU, 0xe0a48d0be9a7453fULL, 0xf9c3f70de26dc2efULL, 0x68ccf180cac5b03cULL},
    {0x38aa207dU, 0xeac0b497876adedfULL, 0xe61e4053c9ba5788ULL, 0xe4de98eda4acd87fULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0x2127dc72b6eb25ebULL, 0x81c37058d15c876fULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0x5e76170332d7cd0aULL, 0x2ba98ddc883aa2abULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0x7ed6627f592fec43ULL, 0xbdf3851b922297eaULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0x8bd8b90e25579a06ULL, 0x1f8ac60a2337a070ULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xa29c66bf361dd379ULL, 0xb46010536b50567cULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xa4ba0587e085ae48ULL, 0x4cec5a465c78fc9cULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xc6596d4faf05d12cULL, 0x6a831bbb9bbf3f87ULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xd5879965d92e80daULL, 0x24c8c856b20d5954ULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xe702eab54ef3c6ecULL, 0x9c77b33495da3514ULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xf446860551e18f8fULL, 0x4a8eed663503353aULL},
    {0x203f720cU, 0xcd4238c6a0c69e32ULL, 0xf6ed26225df0d01dULL, 0x1a5b95a07744b16bULL},
    {0x203f720cU, 0xe0a48d0be9a7453fULL, 0xdb8ad4132cebf885ULL, 0x3932c522116f2c52ULL},
    {0x203f720cU, 0xeac0b497876adedfULL, 0xe61e4053c9ba5788ULL, 0x15a400f81e389e22ULL},
};
struct FieldMapping { std::uint32_t kit_id, field_offset; std::uint64_t source, target; };
inline constexpr FieldMapping piece_fields[] = {
    {0x38aa207dU, 0x00U, 0x01144a44b65471bdULL, 0x7cb30f2385f5dfc1ULL},
    {0x38aa207dU, 0x00U, 0x0387a158d04848f4ULL, 0x72acc94806914431ULL},
    {0x38aa207dU, 0x00U, 0x0fbf63f07f72cd4dULL, 0xace03dcb9bb28b8eULL},
    {0x38aa207dU, 0x00U, 0x1a9053f944788708ULL, 0x93741a38c38e353aULL},
    {0x38aa207dU, 0x00U, 0x1c058e9048d4966cULL, 0xbfc7c5e5b6072ac0ULL},
    {0x38aa207dU, 0x00U, 0x1faef78c66ec2ed1ULL, 0x84259e9cf1dfce15ULL},
    {0x38aa207dU, 0x00U, 0x29099ce94f27b208ULL, 0xfa3fe275555f500eULL},
    {0x38aa207dU, 0x00U, 0x2f66b9373cb58485ULL, 0xe959e2ea146868ceULL},
    {0x38aa207dU, 0x00U, 0x3e43b08cfa451e44ULL, 0x1569aadfe9bb74e7ULL},
    {0x38aa207dU, 0x00U, 0x44f53e9787ca3ffcULL, 0xe74562cfc94ed2b3ULL},
    {0x38aa207dU, 0x00U, 0x55dea3c1dcac7841ULL, 0x6d36cac55535566bULL},
    {0x38aa207dU, 0x00U, 0x593a2a0d7099aef8ULL, 0xef78c166e3cc6760ULL},
    {0x38aa207dU, 0x00U, 0x6612fc2ac51c20d1ULL, 0xd5a879ed1bbd7884ULL},
    {0x38aa207dU, 0x00U, 0x79740c9dbb23a2d8ULL, 0xfc78a4dc5a5352d5ULL},
    {0x38aa207dU, 0x00U, 0x7a3dbeaecacba925ULL, 0x3f44e84458510237ULL},
    {0x38aa207dU, 0x00U, 0x7cbc9209d9736a6bULL, 0x6234440435142775ULL},
    {0x38aa207dU, 0x00U, 0x803419f30e7b8f16ULL, 0xd9ed0d1a042320e1ULL},
    {0x38aa207dU, 0x00U, 0x8d857a8a57a8874bULL, 0x8b99bb6354161787ULL},
    {0x38aa207dU, 0x00U, 0x8df62e0fbe3864c7ULL, 0xed56aa60d9f1c06fULL},
    {0x38aa207dU, 0x00U, 0x9ef5adcfb96fdc57ULL, 0x8e99b9627cb6cf2dULL},
    {0x38aa207dU, 0x00U, 0xa2a205819f79ee41ULL, 0xd49425d58df0409aULL},
    {0x38aa207dU, 0x00U, 0xbc5b49605ab674d7ULL, 0x3d3c9fd7a5b5ed0eULL},
    {0x38aa207dU, 0x00U, 0xc7e47f2d8d5f8b40ULL, 0x059c1d6e991e6644ULL},
    {0x38aa207dU, 0x00U, 0xd2b77c8e346f2fdbULL, 0xe45e9e71944e857bULL},
    {0x38aa207dU, 0x00U, 0xf7f232ee26ec35fbULL, 0x50d197735c64454eULL},
    {0x38aa207dU, 0x00U, 0xf9c3f70de26dc2efULL, 0x68ccf180cac5b03cULL},
    {0x203f720cU, 0x00U, 0xdb8ad4132cebf885ULL, 0x3932c522116f2c52ULL},
};
struct ExpectedBody { std::uint32_t body_type, piece_count; };
struct ExpectedPiece {
    std::uint32_t body_type, slot, piece_type, weight, tone_variations;
    std::uint64_t source_unit;
};
struct TargetKit {
    std::uint32_t id; std::uint64_t archive; std::uint32_t type, passive;
    const ExpectedBody *bodies; std::size_t body_count;
    const ExpectedPiece *pieces; std::size_t piece_count;
    std::size_t expected_unit_changes;
};
inline constexpr ExpectedBody bodies_38aa207d[] = {
    {3U, 7U},
    {0U, 10U},
    {1U, 10U},
};
inline constexpr ExpectedPiece pieces_38aa207d[] = {
    {3U, 1U, 0U, 1U, 0U, 0x3c33cf10a26cbb3eULL},
    {3U, 5U, 1U, 1U, 0U, 0x0fbf63f07f72cd4dULL},
    {3U, 5U, 0U, 1U, 0U, 0x01144a44b65471bdULL},
    {3U, 7U, 0U, 1U, 0U, 0x79740c9dbb23a2d8ULL},
    {3U, 4U, 0U, 1U, 0U, 0xf7f232ee26ec35fbULL},
    {3U, 6U, 0U, 1U, 0U, 0x9ef5adcfb96fdc57ULL},
    {3U, 4U, 1U, 1U, 0U, 0x7a3dbeaecacba925ULL},
    {0U, 2U, 1U, 1U, 0U, 0x6612fc2ac51c20d1ULL},
    {0U, 6U, 1U, 1U, 0U, 0x1faef78c66ec2ed1ULL},
    {0U, 3U, 1U, 1U, 0U, 0x1a9053f944788708ULL},
    {0U, 3U, 2U, 1U, 0U, 0x55dea3c1dcac7841ULL},
    {0U, 7U, 1U, 1U, 0U, 0xbc5b49605ab674d7ULL},
    {0U, 8U, 0U, 1U, 0U, 0x593a2a0d7099aef8ULL},
    {0U, 9U, 0U, 1U, 0U, 0x8df62e0fbe3864c7ULL},
    {0U, 3U, 0U, 1U, 0U, 0x0387a158d04848f4ULL},
    {0U, 2U, 0U, 1U, 0U, 0xf9c3f70de26dc2efULL},
    {0U, 2U, 2U, 1U, 0U, 0x3e43b08cfa451e44ULL},
    {1U, 3U, 1U, 1U, 0U, 0x8d857a8a57a8874bULL},
    {1U, 3U, 2U, 1U, 0U, 0x44f53e9787ca3ffcULL},
    {1U, 8U, 0U, 1U, 0U, 0xa2a205819f79ee41ULL},
    {1U, 3U, 0U, 1U, 0U, 0x2f66b9373cb58485ULL},
    {1U, 2U, 1U, 1U, 0U, 0xc7e47f2d8d5f8b40ULL},
    {1U, 6U, 1U, 1U, 0U, 0x803419f30e7b8f16ULL},
    {1U, 2U, 0U, 1U, 0U, 0xd2b77c8e346f2fdbULL},
    {1U, 7U, 1U, 1U, 0U, 0x7cbc9209d9736a6bULL},
    {1U, 9U, 0U, 1U, 0U, 0x1c058e9048d4966cULL},
    {1U, 2U, 2U, 1U, 0U, 0x29099ce94f27b208ULL},
};
inline constexpr ExpectedBody bodies_203f720c[] = {
    {3U, 1U},
};
inline constexpr ExpectedPiece pieces_203f720c[] = {
    {3U, 0U, 0U, 1U, 0U, 0xdb8ad4132cebf885ULL},
};
inline constexpr TargetKit targets[] = {
    {0x38aa207dU, 0xb0db7f4f0a11debdULL, 0U, 7U, bodies_38aa207d, 3U, pieces_38aa207d, 27U, 26U},
    {0x203f720cU, 0x1bf281b613081b05ULL, 1U, 0U, bodies_203f720c, 1U, pieces_203f720c, 1U, 1U},
};
} // namespace cm14_isolation
