import SwiftUI

/// Shown when the app has no server configured.
/// Guides the user to either scan a QR code or tap an invite link.
struct OnboardingView: View {
    @EnvironmentObject var deepLinkHandler: DeepLinkHandler

    var body: some View {
        ZStack {
            Color(red: 0.06, green: 0.07, blue: 0.09).ignoresSafeArea()

            VStack(spacing: 32) {
                Spacer()

                // Logo
                VStack(spacing: 8) {
                    Image(systemName: "map.fill")
                        .font(.system(size: 56))
                        .foregroundStyle(.blue)
                    Text("SkiTAK")
                        .font(.system(size: 36, weight: .bold))
                        .foregroundStyle(.white)
                    Text("Outdoor group awareness")
                        .font(.subheadline)
                        .foregroundStyle(.gray)
                }

                Spacer()

                // Instructions
                VStack(alignment: .leading, spacing: 20) {
                    InstructionRow(
                        icon: "link",
                        title: "Join a session",
                        body: "Ask your guide for an invite link or QR code. Tap it to set up automatically."
                    )
                    InstructionRow(
                        icon: "location.fill",
                        title: "Allow location access",
                        body: "Choose "Always" so SkiTAK can track you in the background."
                    )
                    InstructionRow(
                        icon: "antenna.radiowaves.left.and.right",
                        title: "You're live",
                        body: "Your guide can see your position on the map in real time."
                    )
                }
                .padding(.horizontal, 28)

                Spacer()

                if let error = deepLinkHandler.enrollmentError {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                        .multilineTextAlignment(.center)
                }

                Text("Waiting for invite link…")
                    .font(.footnote)
                    .foregroundStyle(.gray)
                    .padding(.bottom, 40)
            }
        }
    }
}

private struct InstructionRow: View {
    let icon: String
    let title: String
    let body: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 20))
                .foregroundStyle(.blue)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.white)
                Text(body)
                    .font(.system(size: 13))
                    .foregroundStyle(.gray)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
